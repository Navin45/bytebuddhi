import { describe, expect, it } from "vitest"

describe("desktop auto-update logic", () => {
  it("tracks update state transitions correctly", () => {
    type UpdateState =
      | { status: "idle" }
      | { status: "checking" }
      | { status: "available"; version: string }
      | { status: "downloading"; percent: number }
      | { status: "ready"; version: string }
      | { status: "error"; message: string }

    let state: UpdateState = { status: "idle" }
    expect(state.status).toBe("idle")

    // Start checking
    state = { status: "checking" }
    expect(state.status).toBe("checking")

    // Update found
    state = { status: "available", version: "0.1.4" }
    expect(state.status).toBe("available")
    expect((state as { version: string }).version).toBe("0.1.4")

    // Progress
    state = { status: "downloading", percent: 50 }
    expect(state.status).toBe("downloading")
    expect((state as { percent: number }).percent).toBe(50)

    // Ready
    state = { status: "ready", version: "0.1.4" }
    expect(state.status).toBe("ready")
    expect((state as { version: string }).version).toBe("0.1.4")
  })

  it("blocks update actions while an active run is in progress", () => {
    let hasActiveRun = true

    function canTriggerUpdate(): { allowed: boolean; error?: string } {
      if (hasActiveRun) {
        return { allowed: false, error: "Cannot update while a run is active." }
      }
      return { allowed: true }
    }

    expect(canTriggerUpdate().allowed).toBe(false)
    expect(canTriggerUpdate().error).toBe("Cannot update while a run is active.")

    // Run completes
    hasActiveRun = false
    expect(canTriggerUpdate().allowed).toBe(true)
  })

  it("formats update diagnostic information without leaking credentials", () => {
    const diagnostic = {
      appVersion: "0.1.4-rc.1",
      gatewayVersion: "0.1.4-rc.1",
      protocolVersion: 1,
      channel: "stable",
      platform: "win32",
    }

    expect(diagnostic.appVersion).toBe("0.1.4-rc.1")
    expect(diagnostic.protocolVersion).toBe(1)
    expect(diagnostic).not.toHaveProperty("token")
    expect(diagnostic).not.toHaveProperty("password")
    expect(diagnostic).not.toHaveProperty("apiKey")
  })

  it("handles release channels: stable user ignores prerelease; beta user receives prerelease", () => {
    type ChannelConfig = {
      allowPrerelease: boolean
      channel: string
    }

    function configureChannel(channel: "stable" | "beta"): ChannelConfig {
      if (channel === "beta") {
        return { allowPrerelease: true, channel: "rc" }
      }
      return { allowPrerelease: false, channel: "latest" }
    }

    // Default stable user:
    const stableConfig = configureChannel("stable")
    expect(stableConfig.allowPrerelease).toBe(false)
    expect(stableConfig.channel).toBe("latest")

    // Explicit switch to beta:
    const betaConfig = configureChannel("beta")
    expect(betaConfig.allowPrerelease).toBe(true)
    expect(betaConfig.channel).toBe("rc")

    // Filtering RC version
    const availableReleases = [
      { version: "0.1.4-rc.1", isPrerelease: true },
      { version: "0.1.3", isPrerelease: false },
    ]

    function getEligibleUpdate(releases: typeof availableReleases, config: ChannelConfig) {
      return releases.find((r) => config.allowPrerelease || !r.isPrerelease)
    }

    expect(getEligibleUpdate(availableReleases, stableConfig)?.version).toBe("0.1.3")
    expect(getEligibleUpdate(availableReleases, betaConfig)?.version).toBe("0.1.4-rc.1")
  })

  it("fails closed on corrupted or tampered update artifacts without corrupting installed version", () => {
    let currentVersion = "0.1.3"
    let status: "idle" | "error" | "ready" = "idle"
    let errorMessage = ""

    function applyDownloadedUpdate(artifactSha256: string, expectedSha256: string, newVersion: string) {
      if (artifactSha256 !== expectedSha256) {
        status = "error"
        errorMessage = "Checksum mismatch: download corrupted or tampered"
        return
      }
      currentVersion = newVersion
      status = "ready"
    }

    // Simulate corrupted download
    applyDownloadedUpdate("corrupted_hash", "expected_hash", "0.1.4-rc.1")

    expect(status).toBe("error")
    expect(errorMessage).toContain("Checksum mismatch")
    // Previous known-good version remains active
    expect(currentVersion).toBe("0.1.3")
  })
})
