package main

import "testing"

// Replay the exact VK API response that left the logged clients short of a group.
func TestVKCallsInternalServerErrorRetriesWithoutCaptcha(t *testing.T) {
	for _, message := range []string{"Internal server error", "Internal server error: Unknown error, try later"} {
		t.Run(message, func(t *testing.T) {
			inner := vkCallsAPIError(map[string]interface{}{"error": map[string]interface{}{"error_code": float64(10), "error_msg": message}})
			err := newVKCallsFailure("step3 messages.getAnonymCallToken", vkCallsAPIErrorKind(inner), inner)
			if !vkCallsShouldRetry(err) {
				t.Error("temporary VK code 10 stops all nine workers instead of retrying")
			}
			if vkCallsShouldEscalateCaptcha(err) {
				t.Error("temporary VK code 10 incorrectly requests legacy/captcha restart")
			}
			if _, fatal := asCallUnavailableError(err); fatal {
				t.Error("temporary API failure must not kill the call/hash")
			}
		})
	}
}
