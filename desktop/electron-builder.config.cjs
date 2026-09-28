/**
 * electron-builder production configuration.
 *
 * @see https://www.electron.build/configuration
 */

/** @type {import("electron-builder").Configuration} */
module.exports = {
  appId: "dev.bytebuddhi.desktop",
  productName: "ByteBuddhi",
  artifactName: "${name}-${version}-${os}-${arch}.${ext}",

  // ── Source ─────────────────────────────────────────────────────
  directories: {
    output: "release/${version}",
    buildResources: "build",
  },
  files: [
    "out/**/*",
    "!out/**/*.map",
    "package.json",
  ],
  asar: true,
  asarUnpack: [],

  // ── Publishing / auto-update ──────────────────────────────────
  publish: {
    provider: "github",
    owner: "Navin45",
    repo: "bytebuddhi",
  },

  // ── Windows ───────────────────────────────────────────────────
  win: {
    target: [
      { target: "nsis", arch: ["x64"] },
    ],
    icon: "build/icon.ico",
    signingHashAlgorithms: ["sha256"],
    // Authenticode signing — credentials from CI env:
    //   CSC_LINK:            Base64-encoded PFX or file path
    //   CSC_KEY_PASSWORD:    PFX password
    sign: undefined, // uses default electron-builder signing when CSC_ env vars are set
    verifyUpdateCodeSignature: true,
  },
  nsis: {
    oneClick: false,
    perMachine: false,
    allowToChangeInstallationDirectory: true,
    deleteAppDataOnUninstall: false,
    artifactName: "ByteBuddhi-Setup-${version}.${ext}",
  },

  // ── macOS ─────────────────────────────────────────────────────
  mac: {
    target: [
      { target: "dmg", arch: ["arm64", "x64"] },
      { target: "zip", arch: ["arm64", "x64"] },
    ],
    icon: "build/icon.icns",
    category: "public.app-category.developer-tools",
    hardenedRuntime: true,
    gatekeeperAssess: false,
    entitlements: "build/entitlements.mac.plist",
    entitlementsInherit: "build/entitlements.mac.plist",
    // notarization — credentials from CI env:
    //   APPLE_ID:              Apple ID email
    //   APPLE_APP_SPECIFIC_PASSWORD:  App-specific password or keychain reference
    //   APPLE_TEAM_ID:         Developer Team ID
    notarize: true,
  },
  dmg: {
    artifactName: "ByteBuddhi-${version}-${arch}.${ext}",
  },

  // ── Linux ─────────────────────────────────────────────────────
  linux: {
    target: [
      { target: "AppImage", arch: ["x64"] },
      { target: "deb", arch: ["x64"] },
    ],
    icon: "build/icons",
    category: "Development",
    maintainer: "ByteBuddhi <dev@bytebuddhi.dev>",
    desktop: {
      Name: "ByteBuddhi",
      Comment: "AI Coding Assistant",
      Categories: "Development;IDE;",
      StartupNotify: "true",
    },
  },
  appImage: {
    artifactName: "ByteBuddhi-${version}-${arch}.${ext}",
  },
  deb: {
    artifactName: "bytebuddhi_${version}_${arch}.${ext}",
    depends: ["libgtk-3-0", "libnss3", "libatk-bridge2.0-0"],
  },

  // ── Staged rollout ────────────────────────────────────────────
  // electron-updater reads this from latest.yml / latest-mac.yml
  // Set to 100 for GA; reduce for staged rollouts.
  // generateUpdatesFilesForAllChannels: false,
}
