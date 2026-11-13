#!/bin/bash
set -euo pipefail

for name in IOS_DISTRIBUTION_P12 IOS_DISTRIBUTION_PASSWORD IOS_APP_PROFILE \
    IOS_TUNNEL_PROFILE ASC_KEY_ID ASC_ISSUER_ID ASC_PRIVATE_KEY IOS_BUILD_NUMBER; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing $name" >&2
    exit 1
  fi
done

if [[ ! "$ASC_KEY_ID" =~ ^[A-Z0-9]+$ ]]; then
  echo 'Invalid App Store Connect key ID.' >&2
  exit 1
fi

test -s SilentTunnel/Native/libwdtt.a
umask 077
work="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/silent-testflight.XXXXXX")"
trap 'rm -rf "$work"' EXIT

keychain="$work/signing.keychain-db"
keychain_password="$(openssl rand -hex 24)"
security create-keychain -p "$keychain_password" "$keychain"
security set-keychain-settings -lut 3600 "$keychain"
security unlock-keychain -p "$keychain_password" "$keychain"
security list-keychains -d user -s "$keychain"
printf '%s' "$IOS_DISTRIBUTION_P12" | base64 -D > "$work/distribution.p12"
security import "$work/distribution.p12" -k "$keychain" -f pkcs12 \
  -P "$IOS_DISTRIBUTION_PASSWORD" -T /usr/bin/codesign -T /usr/bin/security
security set-key-partition-list -S apple-tool:,apple: -s -k "$keychain_password" "$keychain" >/dev/null

decode_profile() {
  local name="$1" encoded="$2"
  printf '%s' "$encoded" | base64 -D > "$work/$name.mobileprovision"
  security cms -D -i "$work/$name.mobileprovision" > "$work/$name.plist"
}

decode_profile app "$IOS_APP_PROFILE"
decode_profile tunnel "$IOS_TUNNEL_PROFILE"

# Xcode 16+ and older tooling use different locations for local profiles.
for folder in "$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles" \
    "$HOME/Library/MobileDevice/Provisioning Profiles"; do
  mkdir -p "$folder"
  for name in app tunnel; do
    uuid="$(/usr/libexec/PlistBuddy -c 'Print :UUID' "$work/$name.plist")"
    cp "$work/$name.mobileprovision" "$folder/$uuid.mobileprovision"
  done
done

python3 - "$work" <<'PY'
import plistlib
import sys
from pathlib import Path

work = Path(sys.argv[1])
profiles = {}
teams = set()
for name, bundle in {"app": "io.github.silentvpn3.silentvpn", "tunnel": "io.github.silentvpn3.silentvpn.tunnel"}.items():
    profile = plistlib.loads((work / f"{name}.plist").read_bytes())
    entitlements = profile["Entitlements"]
    if entitlements["application-identifier"].partition(".")[2] != bundle:
        sys.exit(f"The {name} profile must be for {bundle}.")
    if entitlements.get("get-task-allow") or "ProvisionedDevices" in profile or profile.get("ProvisionsAllDevices"):
        sys.exit(f"The {name} profile must be an App Store Connect distribution profile.")
    if "packet-tunnel-provider" not in entitlements.get("com.apple.developer.networking.networkextension", []):
        sys.exit(f"Enable Packet Tunnel on the {name} App ID and regenerate its profile.")
    if "group.io.github.silentvpn3.silentvpn" not in entitlements.get("com.apple.security.application-groups", []):
        sys.exit(f"Add group.io.github.silentvpn3.silentvpn to the {name} App ID and regenerate its profile.")
    profiles[bundle] = profile["Name"]
    teams.add(profile["TeamIdentifier"][0])

if len(teams) != 1:
    sys.exit("Both profiles must belong to the same Apple Developer team.")

options = {
    "method": "app-store-connect",
    "signingStyle": "manual",
    "signingCertificate": "Apple Distribution",
    "teamID": teams.pop(),
    "provisioningProfiles": profiles,
    "manageAppVersionAndBuildNumber": False,
}
(work / "ExportOptions.plist").write_bytes(plistlib.dumps(options))
PY

team="$(/usr/libexec/PlistBuddy -c 'Print :teamID' "$work/ExportOptions.plist")"
app_profile="$(/usr/libexec/PlistBuddy -c 'Print :Name' "$work/app.plist")"
tunnel_profile="$(/usr/libexec/PlistBuddy -c 'Print :Name' "$work/tunnel.plist")"
mkdir "$work/private_keys"
printf '%s' "$ASC_PRIVATE_KEY" | base64 -D > "$work/private_keys/AuthKey_${ASC_KEY_ID}.p8"
unset IOS_DISTRIBUTION_P12 IOS_DISTRIBUTION_PASSWORD IOS_APP_PROFILE IOS_TUNNEL_PROFILE ASC_PRIVATE_KEY

xcodebuild -project Silent.xcodeproj -scheme Silent -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$work/Silent.xcarchive" \
  CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY='Apple Distribution' DEVELOPMENT_TEAM="$team" \
  SILENT_APP_PROFILE="$app_profile" SILENT_TUNNEL_PROFILE="$tunnel_profile" \
  CURRENT_PROJECT_VERSION="$IOS_BUILD_NUMBER" archive

app="$work/Silent.xcarchive/Products/Applications/Silent.app"
test -d "$app/PlugIns/SilentTunnel.appex"
codesign --verify --deep --strict "$app"
xcodebuild -exportArchive -archivePath "$work/Silent.xcarchive" \
  -exportPath "$work/export" -exportOptionsPlist "$work/ExportOptions.plist"

shopt -s nullglob
ipas=("$work"/export/*.ipa)
if [[ "${#ipas[@]}" -ne 1 ]]; then
  echo 'Expected exactly one exported IPA.' >&2
  exit 1
fi

ditto -x -k "${ipas[0]}" "$work/verified-ipa"
exported_app="$work/verified-ipa/Payload/Silent.app"
exported_tunnel="$exported_app/PlugIns/SilentTunnel.appex"
codesign --verify --deep --strict "$exported_app"
codesign -d --entitlements - "$exported_app" > "$work/exported-app-entitlements.plist"
codesign -d --entitlements - "$exported_tunnel" > "$work/exported-tunnel-entitlements.plist"
python3 - "$work" "$exported_app" "$exported_tunnel" <<'PY'
import plistlib
import sys
from pathlib import Path

work, app, tunnel = map(Path, sys.argv[1:])
for target in ("app", "tunnel"):
    entitlements = plistlib.loads((work / f"exported-{target}-entitlements.plist").read_bytes())
    if "packet-tunnel-provider" not in entitlements.get("com.apple.developer.networking.networkextension", []):
        sys.exit(f"Exported {target} lacks the Packet Tunnel entitlement.")
    if "group.io.github.silentvpn3.silentvpn" not in entitlements.get("com.apple.security.application-groups", []):
        sys.exit(f"Exported {target} lacks the Silent VPN app group.")

app_info = plistlib.loads((app / "Info.plist").read_bytes())
tunnel_info = plistlib.loads((tunnel / "Info.plist").read_bytes())
ipad_orientations = {f"UIInterfaceOrientation{value}" for value in (
    "Portrait", "PortraitUpsideDown", "LandscapeLeft", "LandscapeRight",
)}
if not ipad_orientations.issubset(app_info.get("UISupportedInterfaceOrientations~ipad", [])):
    sys.exit("Exported app is missing supported iPad orientations.")
if not tunnel_info.get("CFBundleDisplayName"):
    sys.exit("Exported tunnel is missing its display name.")
print("Exported iOS bundle metadata and VPN entitlements verified.")
PY

(
  cd "$work"
  xcrun altool --upload-app --type ios --file "${ipas[0]}" \
    --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER_ID"
)
