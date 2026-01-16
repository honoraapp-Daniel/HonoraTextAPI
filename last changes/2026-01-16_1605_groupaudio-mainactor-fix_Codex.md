Change title: Fix GroupAudioPlayer deinit main-actor call
Intent: Resolve the main actor isolation warning for removeTimeObserver.
Method: Wrapped the deinit call to removeTimeObserver in a MainActor Task.
Reason: Deinit is nonisolated; calling a @MainActor method directly triggers a concurrency warning.
Files touched: Honora Data Test/Honora Data Test/Audio/GroupAudioPlayer.swift
Tests: Not run (warning-only fix).
Agent signature: Codex
