//go:build ignore

package main

import (
	"crypto/ed25519"
	"encoding/base64"
	"fmt"
	"os"
)

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintf(os.Stderr, "usage: sign-file <path>\n")
		os.Exit(1)
	}

	keyB64 := os.Getenv("RECIPE_SIGNING_KEY")
	if keyB64 == "" {
		fmt.Fprintf(os.Stderr, "RECIPE_SIGNING_KEY not set\n")
		os.Exit(1)
	}

	key, err := base64.StdEncoding.DecodeString(keyB64)
	if err != nil {
		fmt.Fprintf(os.Stderr, "decode key: %v\n", err)
		os.Exit(1)
	}

	data, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintf(os.Stderr, "read file: %v\n", err)
		os.Exit(1)
	}

	sig := ed25519.Sign(ed25519.PrivateKey(key), data)
	sigB64 := base64.StdEncoding.EncodeToString(sig)

	if err := os.WriteFile(os.Args[1]+".sig", []byte(sigB64), 0644); err != nil {
		fmt.Fprintf(os.Stderr, "write sig: %v\n", err)
		os.Exit(1)
	}
}
