// staticflow-llm performs one bounded, tool-free generation using PicoClaw's configured provider.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/sipeed/picoclaw/pkg/config"
	"github.com/sipeed/picoclaw/pkg/logger"
	"github.com/sipeed/picoclaw/pkg/providers"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "generation failed")
		os.Exit(1)
	}
}
func run() error {
	logger.DisableConsole()
	var request struct {
		System string `json:"system"`
		Prompt string `json:"prompt"`
	}
	if err := json.NewDecoder(io.LimitReader(os.Stdin, 128*1024)).Decode(&request); err != nil {
		return err
	}
	cfg, err := config.LoadConfig(os.Getenv("PICOCLAW_CONFIG"))
	if err != nil {
		return err
	}
	provider, model, err := providers.CreateProvider(cfg)
	if err != nil {
		return err
	}
	if closer, ok := provider.(providers.StatefulProvider); ok {
		defer closer.Close()
	}
	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()
	result, err := provider.Chat(ctx, []providers.Message{{Role: "system", Content: request.System}, {Role: "user", Content: request.Prompt}}, nil, model, map[string]any{"max_tokens": 8192, "native_search": false})
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"content": result.Content})
}
