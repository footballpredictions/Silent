package main

import (
	"fmt"
	"testing"
)

func TestStaleAnonTokenFromOkcdnJoin(t *testing.T) {
	inner := fmt.Errorf("error_code=100 PARAM : error.webrtc.auth.anonym_token.outdated (resp: {\"error_code\":100})")
	err := newVKCallsFailure("step5 vchat.joinConversationByLink", vkCallsFailureOKCDN, inner)
	if !vkCallsIsStaleAnonToken(err) {
		t.Fatalf("expected stale token, got %v", err)
	}
	if !vkCallsShouldRetry(err) {
		t.Fatal("stale anonym token must retry join, not stop the group")
	}
	if vkCallsShouldEscalateCaptcha(err) {
		t.Fatal("stale anonym token is not a VK captcha")
	}
}

func TestRealCaptchaStillEscalates(t *testing.T) {
	err := newVKCallsFailure("step2", vkCallsFailureCaptcha, fmt.Errorf("captcha needed"))
	if vkCallsShouldRetry(err) {
		t.Fatal("captcha must not retry vkcalls hosts")
	}
	if !vkCallsShouldEscalateCaptcha(err) {
		t.Fatal("real captcha may escalate")
	}
}
