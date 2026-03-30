package sms

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/sipeed/picoclaw/pkg/bus"
	"github.com/sipeed/picoclaw/pkg/channels"
	"github.com/sipeed/picoclaw/pkg/config"
	"github.com/sipeed/picoclaw/pkg/identity"
	"github.com/sipeed/picoclaw/pkg/logger"
)

type inboundSMS struct {
	Index   int    `json:"index"`
	State   string `json:"state"`
	Number  string `json:"number"`
	Date    string `json:"date"`
	Message string `json:"message"`
}

type unreadResponse struct {
	Messages []inboundSMS `json:"messages"`
}

type sendRequest struct {
	Number  string `json:"number"`
	Message string `json:"message"`
}

type SMSChannel struct {
	*channels.BaseChannel
	config     config.SMSConfig
	httpClient *http.Client
	ctx        context.Context
	cancel     context.CancelFunc
}

func NewSMSChannel(cfg config.SMSConfig, messageBus *bus.MessageBus) (*SMSChannel, error) {
	if cfg.GatewayURL == "" {
		return nil, fmt.Errorf("sms gateway_url is required")
	}

	timeout := cfg.TimeoutSeconds
	if timeout <= 0 {
		timeout = 30
	}

	base := channels.NewBaseChannel(
		"sms",
		cfg,
		messageBus,
		cfg.AllowFrom,
		channels.WithMaxMessageLength(480),
		channels.WithReasoningChannelID(cfg.ReasoningChannelID),
	)

	ch := &SMSChannel{
		BaseChannel: base,
		config:      cfg,
		httpClient: &http.Client{
			Timeout: time.Duration(timeout) * time.Second,
		},
	}
	ch.SetOwner(ch)

	return ch, nil
}

func (c *SMSChannel) Start(ctx context.Context) error {
	logger.InfoC("sms", "Starting SMS channel")

	c.ctx, c.cancel = context.WithCancel(ctx)
	go c.pollLoop()

	c.SetRunning(true)
	logger.InfoC("sms", "SMS channel started")
	return nil
}

func (c *SMSChannel) Stop(ctx context.Context) error {
	logger.InfoC("sms", "Stopping SMS channel")

	if c.cancel != nil {
		c.cancel()
	}

	c.SetRunning(false)
	logger.InfoC("sms", "SMS channel stopped")
	return nil
}

func (c *SMSChannel) Send(ctx context.Context, msg bus.OutboundMessage) error {
	if !c.IsRunning() {
		return channels.ErrNotRunning
	}

	number := strings.TrimSpace(msg.ChatID)
	if number == "" {
		return fmt.Errorf("invalid sms chat ID: %s", msg.ChatID)
	}

	payload := sendRequest{
		Number:  number,
		Message: truncateSMS(msg.Content, 480),
	}

	if err := c.doJSON(ctx, http.MethodPost, "/sms/send", payload, nil); err != nil {
		logger.ErrorCF("sms", "Failed to send SMS", map[string]any{
			"number": number,
			"error":  err.Error(),
		})
		return fmt.Errorf("sms send: %w", channels.ErrTemporary)
	}

	logger.DebugCF("sms", "SMS sent", map[string]any{
		"number": number,
	})

	return nil
}

func (c *SMSChannel) pollLoop() {
        interval := c.config.PollInterval
        if interval <= 0 {
                interval = 15
        }

        logger.InfoCF("sms", "Starting poll loop", map[string]any{
                "interval_seconds": interval,
        })

        ticker := time.NewTicker(time.Duration(interval) * time.Second)
        defer ticker.Stop()

        logger.DebugC("sms", "Running initial pollOnce")
        c.pollOnce()

        for {
                select {
                case <-c.ctx.Done():
                        logger.InfoC("sms", "Stopping poll loop")
                        return
                case <-ticker.C:
                        logger.DebugC("sms", "Ticker fired, running pollOnce")
                        c.pollOnce()
                }
        }
}

func (c *SMSChannel) pollOnce() {
        logger.DebugC("sms", "pollOnce entered")

        ctx, cancel := context.WithTimeout(c.ctx, c.httpClient.Timeout)
        defer cancel()

        var resp unreadResponse
        if err := c.doJSON(ctx, http.MethodGet, "/sms/unread", nil, &resp); err != nil {
                logger.ErrorCF("sms", "Failed to fetch unread SMS", map[string]any{
                        "error": err.Error(),
                })
                return
        }

        logger.DebugCF("sms", "Fetched unread SMS", map[string]any{
                "count": len(resp.Messages),
        })

        for _, sms := range resp.Messages {
                c.handleInboundSMS(sms)
        }
}

func (c *SMSChannel) handleInboundSMS(sms inboundSMS) {
	number := strings.TrimSpace(sms.Number)
	content := strings.TrimSpace(sms.Message)
	if number == "" || content == "" {
		return
	}

	sender := bus.SenderInfo{
		Platform:    "sms",
		PlatformID:  number,
		CanonicalID: identity.BuildCanonicalID("sms", number),
	}

	if !c.IsAllowedSender(sender) {
	logger.DebugCF("sms", "Message rejected by allowlist", map[string]any{
		"number": number,
		"index":  sms.Index,
	})

	if c.config.DeleteAfterRead {
		logger.DebugCF("sms", "Deleting rejected SMS", map[string]any{
			"index": sms.Index,
		})

		if err := c.deleteSMS(c.ctx, sms.Index); err != nil {
			logger.ErrorCF("sms", "Failed to delete rejected SMS", map[string]any{
				"index": sms.Index,
				"error": err.Error(),
			})
		} else {
			logger.DebugCF("sms", "Deleted rejected SMS", map[string]any{
				"index": sms.Index,
			})
		}
	}

	return
}
	peer := bus.Peer{
		Kind: "direct",
		ID:   number,
	}

	messageID := strconv.Itoa(sms.Index)
	chatID := number

	metadata := map[string]string{
		"platform":  "sms",
		"sms_index": strconv.Itoa(sms.Index),
		"number":    number,
		"state":     sms.State,
		"date":      sms.Date,
	}

	logger.DebugCF("sms", "Received SMS", map[string]any{
		"number":  number,
		"index":   sms.Index,
		"preview": truncateSMS(content, 80),
	})

	c.HandleMessage(
		c.ctx,
		peer,
		messageID,
		number,
		chatID,
		content,
		nil,
		metadata,
		sender,
	)

	if c.config.DeleteAfterRead {
		if err := c.deleteSMS(c.ctx, sms.Index); err != nil {
			logger.ErrorCF("sms", "Failed to delete SMS after read", map[string]any{
				"index": sms.Index,
				"error": err.Error(),
			})
		}
	}
}

func (c *SMSChannel) deleteSMS(ctx context.Context, index int) error {
	return c.doJSON(ctx, http.MethodDelete, "/sms/"+strconv.Itoa(index), nil, nil)
}

func (c *SMSChannel) doJSON(ctx context.Context, method, path string, reqBody any, out any) error {
	var body io.Reader

	if reqBody != nil {
		raw, err := json.Marshal(reqBody)
		if err != nil {
			return err
		}
		body = bytes.NewReader(raw)
	}

	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(c.config.GatewayURL, "/")+path, body)
	if err != nil {
		return err
	}

	req.Header.Set("Accept", "application/json")
	if c.config.APIKey != "" {
		req.Header.Set("X-API-Key", c.config.APIKey)
	}
	if reqBody != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("gateway http %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}

	if out == nil || len(raw) == 0 {
		return nil
	}

	return json.Unmarshal(raw, out)
}

func truncateSMS(s string, max int) string {
	s = strings.Join(strings.Fields(strings.TrimSpace(s)), " ")
	if max <= 0 || len([]rune(s)) <= max {
		return s
	}

	r := []rune(s)
	if max <= 3 {
		return string(r[:max])
	}
	return string(r[:max-3]) + "..."
}
