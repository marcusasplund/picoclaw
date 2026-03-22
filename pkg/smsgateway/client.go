package smsgateway

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

type Client struct {
	BaseURL string
	Client  *http.Client
}

func New(baseURL string) *Client {
	return &Client{
		BaseURL: baseURL,
		Client: &http.Client{
			Timeout: 5 * time.Second,
		},
	}
}

func (c *Client) SendSMS(ctx context.Context, number, message string) error {
	body, _ := json.Marshal(map[string]string{
		"number":  number,
		"message": message,
	})

	req, err := http.NewRequestWithContext(ctx, "POST", c.BaseURL+"/sms/send", bytes.NewReader(body))
	if err != nil {
		return err
	}

	req.Header.Set("Content-Type", "application/json")

	resp, err := c.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 300 {
		return fmt.Errorf("send failed: %d", resp.StatusCode)
	}

	return nil
}

type Message struct {
	Index int    `json:"index"`
	From  string `json:"from"`
	Text  string `json:"text"`
}

func (c *Client) FetchUnread(ctx context.Context) ([]Message, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/sms/unread", nil)
	if err != nil {
		return nil, err
	}

	resp, err := c.Client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	var data struct {
		Messages []Message `json:"messages"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return nil, err
	}

	return data.Messages, nil
}

func (c *Client) Delete(ctx context.Context, index int) error {
	req, err := http.NewRequestWithContext(ctx, "DELETE", fmt.Sprintf("%s/sms/%d", c.BaseURL, index), nil)
	if err != nil {
		return err
	}

	resp, err := c.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	return nil
}
