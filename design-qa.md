# OpenBBQ Review UI — Design QA

Final result: passed

## Visual truth

- Selected direction: precision review console (option 1)
- Reference: `/Users/shino/.codex/generated_images/019f5748-07a1-7fa0-817f-82c56c2c12c3/exec-40ba0ef8-9eed-4ab9-803d-c7eba4da5176.png`
- Implementation capture: `/Users/shino/.codex/visualizations/2026/07/12/019f5748-07a1-7fa0-817f-82c56c2c12c3/openbbq-review-option1-final.png`
- Side-by-side comparison: `/Users/shino/.codex/visualizations/2026/07/12/019f5748-07a1-7fa0-817f-82c56c2c12c3/openbbq-review-option1-comparison.png`
- Comparison viewport: 1280 × 720
- Captured state: dark theme, Simplified Chinese UI, `zh` worksheet, cue #3 selected, selected-cue timeline fit at 24×. The current editor supports up to 96×.

## Fidelity review

| Surface | Evidence and result |
| --- | --- |
| Layout | Matches the selected two-column console: media and waveform on the left; cue table and selected-cue inspector on the right. The 59/41 split preserves the reference hierarchy at 1280 × 720. |
| Spacing | Compact 56px header, video-hover playback controls, a separate single-row subtitle edit deck, 42px timeline toolbar, and dense table rows avoid stacking unrelated controls below the media. |
| Typography | Geist is used for UI text and JetBrains Mono for timecodes and numeric timing data. Source/translation hierarchy, table truncation, and fixed-width time values remain scannable. |
| Color | Neutral near-black surfaces with OpenBBQ red for playhead, selected cue, active controls, and focus. Light theme uses the same semantic token relationships without gradients or glass effects. |
| Icons | All transport and structural editing controls use Lucide icons with shadcn/Base UI tooltips and consistent sizing. No handwritten SVG, emoji, or CSS icon substitutes remain. |
| Media | The real review video is rendered at its native aspect ratio with bilingual subtitle overlay and no stretched or placeholder imagery. |
| Editor | Source and translation stay visible; timing fields and primary review actions are prioritized. Review notes are disclosed from a compact icon instead of occupying persistent vertical space. |
| Timeline | The selected cue is fit with context on load, supports up to 96× zoom, has visible edge handles, playhead and snap guides, light/dark palettes, horizontal wheel panning, and legal neighbor-bound trimming. |
| Accessibility | Icon buttons have accessible names and tooltips, form controls are labelled, focus rings use the brand token, reduced motion is respected, and status is exposed through semantic status text. |
| Viewport scope | This is intentionally a desktop precision editor with a 1080px minimum workspace. The selected reference and primary QA viewport are desktop; mobile editing is outside this feature's scope. |

## Interaction evidence

- Switched between English and Simplified Chinese; `document.lang`, visible copy, and local persistence updated correctly.
- Switched between light and dark themes; token state and local persistence survived reload.
- Verified unreviewed/reviewed filtering against the 166-cue real workspace.
- Verified snap off/on state, selected-cue fit, delete confirmation/cancel, and labelled icon controls.
- Nudged cue #3 start by exactly +100ms, observed the saved state, confirmed `cues.json` changed from `5.99` to `6.09`, then restored it with Undo.
- Dragged a cue edge beyond its legal neighbor boundary. The final implementation preserved the workspace's inferred minimum gap and completed without `invalid_timeline`.
- Production assets loaded from the packaged review server, and no runtime error state surfaced during the final interaction pass.
- Component regression coverage verifies that playback controls live inside the media panel while structural subtitle actions remain in the edit toolbar; timeline-model coverage verifies the 96× zoom cap.
- Player regression coverage verifies 5-second arrow-key seeking, up/down volume adjustment, and temporary 2× playback while holding the right arrow.
- Player regression coverage verifies that clicking the video surface invokes playback without requiring the play button.

## Findings and fixes

1. Initial full-media zoom made cue blocks too narrow for timing work. Fixed by fitting the first selected cue with context on load while preserving explicit zoom controls.
2. Cue-list timestamps exposed floating-point formatting. Fixed with stable `mm:ss.mmm` formatting.
3. Edge dragging could cross the workspace `min_gap` and trigger `invalid_timeline`. Fixed with tested neighbor-bound constraints shared by drag and nudge interactions.
4. Persistent review notes displaced the primary review actions below the 720px viewport. Fixed by moving notes behind a labelled disclosure icon.
5. Raw select values leaked English (`bilingual`, `0.1`) into the Chinese UI. Fixed by rendering localized overlay labels and human-readable millisecond steps.
6. Playback controls initially remained visually fixed while paused and resembled a transplanted toolbar. Replaced them with a video-edge gradient layer: progress sits on its own full-width rail, standard controls are compact beneath it, and the entire layer appears only on media hover or keyboard-visible focus. Cue looping moved back to the timeline toolbar.
7. The 24× timeline cap was insufficient for fine timing work on short cues. Raised the cap to 96× and made zoom-button increments adaptive so coarse ranges remain quick to traverse.
8. The media ref callback was recreated on every playback-time render and rewrote `currentTime`, causing repeated micro-seeks and visibly uneven playback. Replaced it with a stable attachment callback and an imperative time ref; ordinary renders no longer seek the media. The video surface now toggles playback directly.
9. The first overlay pass exposed every control at once and left timeline labels competing for space. Reorganized player controls into left/right clusters, made the progress rail full-width, collapsed the volume rail until interaction, removed redundant select chevrons, and reduced snap/fit actions to labelled icon controls.
10. The control row inherited centered cross-axis sizing, so playback and fullscreen floated around the middle instead of anchoring to the player edges. Made the row full-width with explicit start/end clusters. Volume now uses a purpose-built narrow vertical panel with a numeric level, thin track, and compact thumb; removing the generic Slider and volume tooltip prevents the oversized hover disc and tooltip collision.
11. Media and editing shortcuts originally shared a stateful listener, allowing cue/autosave updates to interrupt a held arrow key. Split media shortcuts into a stable listener, added visible `±5s` and `±2×` feedback, and removed the browser's default blue video focus outline.
12. Millisecond precision made the player clock noisy even though it remains necessary for cue editing. The player now displays `HH:MM:SS`; timeline and cue timing continue to use millisecond precision.
13. The browser's native vertical range offset its thumb from the custom track. Replaced it with a deterministic pointer/keyboard slider whose track, fill, and thumb share one center axis. Playback speed now uses the same 48px hover-popover pattern as volume and opens without a trigger click.
14. Pointer interaction left the volume slider focused, and `:focus-within` kept its popover open while hovering speed. Pointer releases now blur the control, mouse visibility is hover-only, and persistent focus expansion is limited to keyboard `:focus-visible` navigation.
15. Timeline playback originally depended on low-frequency media `timeupdate`, shifted its waveform window on every tick, and reset/redrew one high-DPI canvas for both static and dynamic content. The viewport now remains stable inside follow margins, waveform/word requests occur only when that window moves, and a dedicated animation-frame overlay renders the live playhead.
16. Cue dragging originally stored every pointer move in React state and redrew the static waveform. Drag drafts now live in a ref and render only on the overlay; the static layer redraws once when dragging starts and once when it commits.
17. Base UI Slider exposes `data-orientation="horizontal"`, while the generated classes targeted a missing `data-horizontal` attribute. Corrected the orientation selectors and added an explicit 96px zoom track, filled range, and aligned thumb.
18. The zoom slider root had no shared cross-axis height with its control, leaving the rail visually pinned above the toolbar center. The root and control now share a 32px flex box and center the track and thumb on the same vertical axis.
19. Waveform peaks were stretched across the canvas by array index, ignoring the response's absolute `start` and `end` times. During horizontal panning, cue geometry therefore moved immediately while the waveform waited for a replacement request. Peaks now map to absolute media time and load in a three-viewport buffer, so waveform and cues pan together while refetches happen only when the buffer boundary changes.

No unresolved blocking or high-severity fidelity findings remain.
