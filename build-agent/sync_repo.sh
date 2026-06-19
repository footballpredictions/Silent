#!/usr/bin/env bash
# Синхронизация клона pc/android перед сборкой (без локальных правок).
set -euo pipefail

PLATFORM="${1:?platform required: pc|android}"
BRANCH="$PLATFORM"
REPO_URL="${BUILD_AGENT_GIT_URL:-https://github.com/footballpredictions/Silent.git}"
ROOT="${BUILD_AGENT_ROOT:-/app/build-agent}"
WORKSPACE="${BUILD_AGENT_WORKSPACE:-$ROOT/workspace}"
DIR="$WORKSPACE/$PLATFORM"

mkdir -p "$WORKSPACE"

clone_url() {
  if [[ -f "$ROOT/secrets/git_token" ]]; then
    local tok
    tok="$(tr -d '[:space:]' < "$ROOT/secrets/git_token")"
    echo "${REPO_URL/https:\/\//https://${tok}@}"
  else
    echo "$REPO_URL"
  fi
}

if [[ ! -d "$DIR/.git" ]]; then
  echo "[sync] clone $BRANCH -> $DIR"
  git clone -b "$BRANCH" --depth 1 "$(clone_url)" "$DIR"
  exit 0
fi

cd "$DIR"
git remote set-url origin "$(clone_url)"
git fetch origin "$BRANCH" --depth 1
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"
if [[ "$LOCAL" != "$REMOTE" ]]; then
  echo "[sync] update $PLATFORM $LOCAL -> $REMOTE"
  git reset --hard "origin/$BRANCH"
else
  echo "[sync] $PLATFORM up to date ($LOCAL)"
fi
