package slack

import (
	"bytes"
	"context"
	"encoding/json"
	"os/exec"
	"strings"
	"time"
)

// The process receives authenticated Slack event fields, never model-generated arguments.
// Approval commands are intercepted before they enter the general agent conversation.
func (c *SlackChannel) handleStaticFlow(user, channel, thread, timestamp, content string) bool {
	if len(c.config.StaticFlowCommand) == 0 {
		return false
	}
	content = strings.TrimSpace(c.stripBotMention(content))
	fields := strings.Fields(content)
	if len(fields) == 0 {
		return false
	}
	switch strings.ToLower(fields[0]) {
	case "bygg", "build", "plan-ok", "approve", "continue", "deploy", "jobb", "status", "stoppa", "stop", "details", "release", "delete", "delete-ok":
	default:
		return false
	}
	if thread == "" {
		thread = timestamp
	}
	request, _ := json.Marshal(map[string]string{"user": user, "channel": channel, "thread": thread, "event": timestamp, "text": content})
	go func() {
		parent := c.ctx
		if parent == nil {
			parent = context.Background()
		}
		ctx, cancel := context.WithTimeout(parent, 8*time.Minute)
		defer cancel()
		cmd := exec.CommandContext(ctx, c.config.StaticFlowCommand[0], c.config.StaticFlowCommand[1:]...)
		cmd.Stdin = bytes.NewReader(request)
		output, err := cmd.Output()
		reply := "The project command failed. Use `status` for the saved state."
		if err == nil && len(output) > 0 && len(output) < 35000 {
			reply = string(output)
		}
		_ = c.postTextFn(ctx, channel, thread, reply)
	}()
	return true
}
