package slack

import (
	"context"
	"encoding/json"
	"github.com/sipeed/picoclaw/pkg/config"
	"testing"
	"time"
)

func TestStaticFlowDisabledDoesNotIntercept(t *testing.T) {
	c := &SlackChannel{config: &config.SlackSettings{}}
	if c.handleStaticFlow("U", "D", "T", "1", "plan-ok job hash") {
		t.Fatal("disabled workflow intercepted message")
	}
}
func TestStaticFlowIgnoresConversation(t *testing.T) {
	c := &SlackChannel{config: &config.SlackSettings{StaticFlowCommand: []string{"must-not-run"}}}
	for _, msg := range []string{"", "hej", "jag säger deploy", "plan-okay 1 2"} {
		if c.handleStaticFlow("U", "D", "T", "1", msg) {
			t.Fatalf("intercepted %q", msg)
		}
	}
}

func TestStaticFlowPassesEventWithoutShellEvaluation(t *testing.T) {
	replies := make(chan string, 1)
	c := &SlackChannel{config: &config.SlackSettings{StaticFlowCommand: []string{"/bin/cat"}},
		postTextFn: func(_ context.Context, channel, thread, text string) error {
			if channel != "D1" || thread != "123" {
				t.Errorf("unexpected destination %s/%s", channel, thread)
			}
			replies <- text
			return nil
		},
	}
	content := "bygg app-test $(touch /should-not-exist)"
	if !c.handleStaticFlow("U1", "D1", "", "123", content) {
		t.Fatal("command not intercepted")
	}
	select {
	case reply := <-replies:
		var event map[string]string
		if err := json.Unmarshal([]byte(reply), &event); err != nil {
			t.Fatal(err)
		}
		if event["text"] != content || event["user"] != "U1" || event["thread"] != "123" {
			t.Fatalf("wrong event: %v", event)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("no command response")
	}
}
