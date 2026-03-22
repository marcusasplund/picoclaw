package tools

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"github.com/sipeed/picoclaw/pkg/bus"
	"github.com/sipeed/picoclaw/pkg/config"
)

var e164PhoneRe = regexp.MustCompile(`^\+[1-9][0-9]{6,18}$`)

type SendSMSTool struct {
	bus         *bus.MessageBus
	allowedTo   map[string]struct{}
	maxLength   int
	channelName string
}

func NewSendSMSTool(messageBus *bus.MessageBus, cfg *config.Config) *SendSMSTool {
	allowed := make(map[string]struct{})
	for _, n := range cfg.Channels.SMS.AllowFrom {
		n = normalizePhoneNumber(n)
		if n != "" {
			allowed[n] = struct{}{}
		}
	}

	return &SendSMSTool{
		bus:         messageBus,
		allowedTo:   allowed,
		maxLength:   480,
		channelName: "sms",
	}
}

func (t *SendSMSTool) Name() string {
	return "send_sms"
}

func (t *SendSMSTool) Description() string {
	return "Send an SMS message to a phone number using the configured sms channel. Use E.164 format, for example +46760309390."
}

func (t *SendSMSTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"number": map[string]any{
				"type":        "string",
				"description": "Recipient phone number in E.164 format, for example +46760309390.",
			},
			"message": map[string]any{
				"type":        "string",
				"description": "The SMS text to send.",
			},
		},
		"required": []string{"number", "message"},
	}
}

func (t *SendSMSTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	if t.bus == nil {
		return ErrorResult("sms bus is not available")
	}

	number := getStringArg(args, "number")
	message := getStringArg(args, "message")

	normalizedNumber, err := validateAndNormalizeNumber(number)
	if err != nil {
		return ErrorResult(err.Error())
	}

	message = normalizeSMSBody(message)
	if message == "" {
		return ErrorResult("message is required")
	}

	if len(t.allowedTo) > 0 {
		if _, ok := t.allowedTo[normalizedNumber]; !ok {
			return ErrorResult(fmt.Sprintf("sending sms to %s is not allowed", normalizedNumber))
		}
	}

	if runeLen(message) > t.maxLength {
		message = truncateRunes(message, t.maxLength)
	}

	out := bus.OutboundMessage{
		Channel: t.channelName,
		ChatID:  normalizedNumber,
		Content: message,
	}

	if err := t.bus.PublishOutbound(ctx, out); err != nil {
		return ErrorResult(fmt.Sprintf("failed to queue sms: %v", err))
	}

	return UserResult(fmt.Sprintf("SMS queued to %s", normalizedNumber))
}

func getStringArg(args map[string]any, key string) string {
	v, ok := args[key]
	if !ok || v == nil {
		return ""
	}
	s, ok := v.(string)
	if !ok {
		return ""
	}
	return strings.TrimSpace(s)
}

func normalizePhoneNumber(s string) string {
	s = strings.TrimSpace(s)
	s = strings.ReplaceAll(s, " ", "")
	s = strings.ReplaceAll(s, "-", "")
	s = strings.ReplaceAll(s, "(", "")
	s = strings.ReplaceAll(s, ")", "")
	return s
}

func validateAndNormalizeNumber(input string) (string, error) {
	n := normalizePhoneNumber(input)
	if n == "" {
		return "", fmt.Errorf("number is required")
	}

	if strings.HasPrefix(n, "+460") {
		return "", fmt.Errorf("invalid phone number format: use +46 without the leading 0, for example +46760309390")
	}

	if !strings.HasPrefix(n, "+") {
		return "", fmt.Errorf("phone number must be in international E.164 format, for example +46760309390")
	}

	if !e164PhoneRe.MatchString(n) {
		return "", fmt.Errorf("invalid phone number format: expected E.164, for example +46760309390")
	}

	return n, nil
}

func normalizeSMSBody(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}

	lines := strings.Split(s, "\n")
	for i := range lines {
		lines[i] = strings.Join(strings.Fields(lines[i]), " ")
	}
	return strings.TrimSpace(strings.Join(lines, "\n"))
}

func truncateRunes(s string, max int) string {
	if max <= 0 {
		return ""
	}
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	if max <= 3 {
		return string(r[:max])
	}
	return string(r[:max-3]) + "..."
}

func runeLen(s string) int {
	return len([]rune(s))
}
