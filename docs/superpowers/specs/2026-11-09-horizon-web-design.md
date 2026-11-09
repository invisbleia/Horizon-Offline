# Horizon in the Browser — Design

Date: 2026-11-09
Status: draft, awaiting operator approval
Fork: invisbleia/horizon-cracked (this repository)

## Intent and why

Players should open a tab on the operator's site and play the full single-player
Horizon game (Rust Minecraft Java 26.3) right there — no download, no install —
and their worlds should persist between visits. This fork's identity is
"play easily, like TLauncher"; the browser client is the next step of that.
Multiplayer is explicitly out of scope for this project.

## Goals

- The game boots in a browser tab: menus, world creation, playing, saving.
- Worlds, playerdata, and options save to the browser and survive reloads.
- Vanilla assets are served by the site and cached after a one-time download.
- Runs on current Chrome/Edge/Firefox/Safari with WebGPU; other browsers get a
  clear "can't run this" page, not a broken page.
- The desktop client keeps building and behaving exactly as today.

## Non-goals

- Multiplayer of any kind (LAN, dedicated, relay) — later project.
- The GPUI launcher on the web — the launcher stays a desktop program.
- Touch/mobile controls.
- Mods, cosmetics, telemetry ingest in the browser build.

## Anti-goals (failure even if it works)

- Forking gameplay logic: the web client must reuse the same gameplay and
  rendering libraries, not a copy that drifts.
- Regressing the desktop build or its CI.

## Constraints

- Browsers cannot open raw TCP: fine while multiplayer is out of scope, but the
  design must not make the future relay harder.
- Threads on wasm need SharedArrayBuffer, i.e. cross-origin isolation
  (COOP/COEP headers). GitHub Pages cannot set headers; Cloudflare Pages can
  (`_headers` file). The site hosts on Cloudflare Pages; `coi-serviceworker` is
  the fallback shim for static hosts.
- wgpu 30.0.1 (already a dependency, backend-switched per platform by features)
  gains a `webgpu` feature; winit 0.30.13 supports the web platform natively.
- `pollster::block_on` cannot run on the wasm main thread; any blocking call in
  the entry path needs a web-shaped equivalent.
- cpal 0.16 (optional `audio` feature) ships a Web Audio backend on wasm.
- The repo never commits Mojang files (AGENTS.md): the site serves the prepared
  vanilla asset pack built by the operator's own machine (`horizon-prepare`),
  the repository itself carries none of it.
- WebAssembly memory/compile limits favor splitting or lazy-loading big data;
  the asset pack must not be inlined into the wasm binary.

## Approaches considered

1. **Real port — new `horizon-client-web` workspace crate reusing the game's
   libraries, with browser shims behind `cfg(target_family = "wasm")`.**
   Desktop untouched; the web crate owns the entry, the canvas loop, the OPFS
   file layer, the asset fetch/cache, and the WebGPU feature wiring.
   Trades off: real work on shims and build plumbing, but no drift and the
   only path that ends at "full game". **Chosen.**
2. **Stream the desktop game to the browser.** Fast to ship, but monthly GPU
   server cost, input latency, and it is not a real browser game. Rejected:
   against the "easy for players, no server bills" intent.
3. **Embed a different browser Minecraft (Eaglercraft-style) on the site.**
   Not Horizon, not this codebase, licence mess. Rejected.

## The parts decided (with reasons)

- **Packaging:** `crates/horizon-client-web` — wasm-bindgen entry crate that
  depends on the existing libraries (horizon-client-lib, horizon-client-render
  layers, horizon-world, horizon-core, horizon-protocol, horizon-assets). The
  desktop binary (`horizon-client`) gains no wasm code. Platform differences in
  shared crates go behind `cfg(target_family = "wasm")` shims, one subsystem at
  a time, so desktop builds never link the shims.
- **Rendering:** a `webgpu` feature mirroring the existing
  `vulkan`/`metal`/`dx12`/`gles` feature pattern; on wasm, the surface comes
  from the winit canvas. Whether the vendored `third_party/wgpu-hal` patch
  (Windows Vulkan fixes) is inert on the web backend is a builder check.
- **Files and saves:** a small virtual-filesystem trait at the few places that
  touch the disk for saves, options, and logs; the web impl stores bytes in
  **OPFS** (it is a real, durable, per-origin filesystem). Save formats do not
  change: regions, NBT, level.dat land in OPFS paths shaped like game folders.
  Worlds persist per site origin; clearing site data clears them (the UI says
  so, once).
- **Assets:** the site serves the prepared pack as an archive plus a manifest;
  first launch fetches it once (progress screen), caches it in Cache Storage,
  and every later launch reads it through the same VFS shim. Pack builds are
  not committed to the repo.
- **Threads:** wasm atomics + threads behind a feature; the site serves
  COOP/COEP so SharedArrayBuffer works. The server thread stays a real thread;
  the streaming worker pool scales down on web. If a subsystem fights the
  threading model, the builder may run it on the main thread first and notes it
  in the plan.
- **Audio:** enable the existing `audio` feature with cpal's web backend.
- **Hosting:** Cloudflare Pages, `_headers` for COOP/COEP and correct MIME for
  `.wasm`; a WebGPU-capability gate page for unsupported browsers.
- **Order of work (each slice is shippable knowledge):**
  0. Spike, throwaway: compile the client libs for `wasm32-unknown-unknown`
     and light a canvas through wgpu/winit in a tab. No gameplay. Answers the
     build-plumbing questions before any shim work.
  1. Boot the real menus in the tab (fonts, UI drawing) via the shim layers.
  2. Create a world, stream chunks, walk around, break/place.
  3. Save/load worlds in OPFS; options too.
  4. Audio, full-game polish, performance pass, the capability gate page.

## Left to the builder

- Exact wgpu feature set and target flags for wasm; the atomics build pipeline.
- How much of horizon-client-render compiles unchanged (expected: most).
- Worker pool sizing, rAF-driven tick pacing, and the asset-cache format.
- The spike's findings feed the plan; the spike itself is throwaway.
