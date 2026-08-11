package telemost

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/google/uuid"
)

const (
	apiBase       = "https://cloud-api.yandex.ru/telemost_front/v2/telemost"
	roomURLPrefix = "https://telemost.yandex.ru/j/"
)

// ConnectionInfo is the Telemost conference join metadata (Goolom).
type ConnectionInfo struct {
	RoomID       string `json:"room_id"`
	PeerID       string `json:"peer_id"`
	Credentials  string `json:"credentials"`
	ClientConfig struct {
		MediaServerURL string `json:"media_server_url"`
	} `json:"client_configuration"`
}

// NormalizeRoomURL accepts bare room id or full https://telemost.yandex.ru/j/… URL.
func NormalizeRoomURL(room string) string {
	room = strings.TrimSpace(room)
	if room == "" {
		return ""
	}
	if strings.HasPrefix(room, "https://") || strings.HasPrefix(room, "http://") {
		return room
	}
	return roomURLPrefix + room
}

// GetConnectionInfo fetches join credentials for an existing Telemost room (no create).
func GetConnectionInfo(ctx context.Context, room, displayName string) (*ConnectionInfo, error) {
	roomURL := NormalizeRoomURL(room)
	if roomURL == "" {
		return nil, errors.New("telemost: empty room")
	}
	if displayName == "" {
		displayName = "SilentVPN"
	}
	u := fmt.Sprintf("%s/conferences/%s/connection", apiBase, url.QueryEscape(roomURL))
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	q := req.URL.Query()
	q.Set("next_gen_media_platform_allowed", "true")
	q.Set("display_name", displayName)
	q.Set("waiting_room_supported", "true")
	req.URL.RawQuery = q.Encode()
	req.Header.Set("User-Agent", "Mozilla/5.0 (X11; Linux x86_64; rv:149.0) Gecko/20100101 Firefox/149.0")
	req.Header.Set("Accept", "*/*")
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Client-Instance-Id", uuid.New().String())
	req.Header.Set("X-Telemost-Client-Version", "187.1.0")
	req.Header.Set("Idempotency-Key", uuid.New().String())
	req.Header.Set("Origin", "https://telemost.yandex.ru")
	req.Header.Set("Referer", "https://telemost.yandex.ru/")

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("telemost api: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("telemost api status %d", resp.StatusCode)
	}
	var info ConnectionInfo
	if err := json.NewDecoder(resp.Body).Decode(&info); err != nil {
		return nil, err
	}
	if info.RoomID == "" || info.PeerID == "" || info.ClientConfig.MediaServerURL == "" {
		return nil, errors.New("telemost: incomplete connection info")
	}
	return &info, nil
}
