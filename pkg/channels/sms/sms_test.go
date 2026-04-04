package sms

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/sipeed/picoclaw/pkg/bus"
	"github.com/sipeed/picoclaw/pkg/config"
)

func TestSMSChannelSendPostsExpectedPayload(t *testing.T) {
	var gotMethod string
	var gotPath string
	var gotAuth string
	var gotBody sendRequest

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotMethod = r.Method
		gotPath = r.URL.Path
		gotAuth = r.Header.Get("X-API-Key")
		if err := json.NewDecoder(r.Body).Decode(&gotBody); err != nil {
			t.Fatalf("decode request body: %v", err)
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	ch, err := NewSMSChannel(config.SMSConfig{
		GatewayURL: srv.URL,
		APIKey:     "test-key",
	}, bus.NewMessageBus(16))
	if err != nil {
		t.Fatalf("NewSMSChannel() error = %v", err)
	}

	if err := ch.Start(context.Background()); err != nil {
		t.Fatalf("Start() error = %v", err)
	}
	defer ch.Stop(context.Background())

	_, err = ch.Send(context.Background(), bus.OutboundMessage{
		ChatID:  "+46701234567",
		Content: "hello from test",
	})
	if err != nil {
		t.Fatalf("Send() error = %v", err)
	}

	if gotMethod != http.MethodPost {
		t.Fatalf("method = %q, want %q", gotMethod, http.MethodPost)
	}
	if gotPath != "/sms/send" {
		t.Fatalf("path = %q, want %q", gotPath, "/sms/send")
	}
	if gotAuth != "test-key" {
		t.Fatalf("X-API-Key = %q, want %q", gotAuth, "test-key")
	}
	if gotBody.Number != "+46701234567" {
		t.Fatalf("number = %q, want %q", gotBody.Number, "+46701234567")
	}
	if gotBody.Message != "hello from test" {
		t.Fatalf("message = %q, want %q", gotBody.Message, "hello from test")
	}
}

func TestSMSChannelSendRequiresChatID(t *testing.T) {
	ch, err := NewSMSChannel(config.SMSConfig{
		GatewayURL: "http://example.test",
	}, bus.NewMessageBus(16))
	if err != nil {
		t.Fatalf("NewSMSChannel() error = %v", err)
	}

	if err := ch.Start(context.Background()); err != nil {
		t.Fatalf("Start() error = %v", err)
	}
	defer ch.Stop(context.Background())

	if _, err := ch.Send(context.Background(), bus.OutboundMessage{Content: "missing chat id"}); err == nil {
		t.Fatal("Send() error = nil, want non-nil")
	}
}
