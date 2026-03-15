# Visual Verification Block — Web

This block is injected for tasks with the `frontend` label.

## Additional Review Requirements

When reviewing frontend changes, you MUST also verify:

### Visual Correctness
- Does the UI match the design specification (if provided)?
- Are components properly aligned and spaced?
- Does the layout work at different viewport widths?
- Are interactive states (hover, focus, active, disabled) handled?

### Accessibility
- Do all images have alt text?
- Is keyboard navigation working?
- Are ARIA labels present where needed?
- Is color contrast sufficient (WCAG AA)?
- Do form inputs have associated labels?

### Responsiveness
- Test at 320px, 768px, 1024px, 1440px widths
- Are touch targets at least 44x44px on mobile?
- Does content reflow properly (no horizontal scroll)?

### Browser Compatibility
- Check for CSS features that may need prefixes
- Verify no IE-specific code unless required
