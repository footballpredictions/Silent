package client

import (
	"errors"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/pion/logging"
	"github.com/pion/stun/v3"
	"github.com/pion/turn/v5/internal/proto"
)

func refreshFixture(t *testing.T, code stun.ErrorCode) *allocation {
	t.Helper()
	transport := &mockClient{performTransaction: func(_ *stun.Message, _ net.Addr, _ bool) (TransactionResult, error) {
		var attributes []stun.Setter
		if code == 0 {
			attributes = []stun.Setter{stun.TransactionID, stun.NewType(stun.MethodRefresh, stun.ClassSuccessResponse),
				proto.Lifetime{Duration: 600 * time.Second}}
		} else {
			attributes = []stun.Setter{stun.TransactionID, stun.NewType(stun.MethodRefresh, stun.ClassErrorResponse),
				stun.ErrorCodeAttribute{Code: code}, stun.NewNonce("fresh-nonce")}
		}
		message, err := stun.Build(attributes...)
		return TransactionResult{Msg: message}, err
	}}
	return &allocation{client: transport, username: stun.NewUsername("fixture"), realm: stun.NewRealm("fixture"),
		_nonce: stun.NewNonce("old-nonce"), integrity: stun.NewLongTermIntegrity("fixture", "fixture", "fixture"),
		log: logging.NewDefaultLoggerFactory().NewLogger("refresh-test")}
}

func TestIOSRefreshRejectsExpiredOrDeniedAllocation(t *testing.T) {
	for _, code := range []stun.ErrorCode{403, 437} {
		fixture := refreshFixture(t, code)
		err := fixture.refreshAllocation(600*time.Second, false)
		if err == nil {
			t.Errorf("TURN error %d reported as successful renewal; expired allocation stays active", code)
		} else if !strings.Contains(err.Error(), "TURN refresh rejected") {
			t.Errorf("unexpected refresh error: %v", err)
		}
	}
}

func TestIOSRefreshRetainsSuccessAndStaleNonceRetry(t *testing.T) {
	fixture := refreshFixture(t, 0)
	if err := fixture.refreshAllocation(600*time.Second, false); err != nil || fixture.lifetime() != 600*time.Second {
		t.Fatalf("successful refresh changed: %v", err)
	}
	fixture = refreshFixture(t, stun.CodeStaleNonce)
	if err := fixture.refreshAllocation(600*time.Second, false); !errors.Is(err, errTryAgain) || string(fixture.nonce()) != "fresh-nonce" {
		t.Fatalf("stale nonce retry changed: %v", err)
	}
}
