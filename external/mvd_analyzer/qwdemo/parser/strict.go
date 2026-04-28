package parser

import (
	"errors"
	"fmt"
)

// ErrStrict is the sentinel error returned by ParseOne / Parse when
// strict mode is active and the parser encounters a condition it would
// otherwise silently downgrade to a Warning. Callers can use
// errors.Is to detect it.
//
// Strict mode is an additive layer over diagnostic mode: the same
// warn() calls that populate DiagnosticWarnings() in diagnostic mode
// also set a sticky parseErr in strict mode, which ParseOne() returns
// once the current message is processed.
//
// This is the integration hook for demopasha's invariant #1
// ("unknown byte = hard failure, never `continue`"). See
// docs/superpowers/specs/2026-04-28-mvd-analyzer-integration.md in
// the parent demopasha repo.
var ErrStrict = errors.New("parser: strict mode violation")

// StrictError wraps a Warning into an error so callers can extract the
// original time / type / message without re-parsing the text.
type StrictError struct {
	Warning Warning
}

func (e *StrictError) Error() string {
	return fmt.Sprintf("strict: %s", e.Warning.String())
}

func (e *StrictError) Is(target error) bool {
	return target == ErrStrict
}

// SetStrictMode enables strict-mode error promotion. When true, every
// warn(...) records a Warning AND sets a sticky parseErr. ParseOne()
// returns that error after the message is processed (so the caller
// gets at least one well-formed event from the message before the
// failure surfaces, mirroring the natural "process then signal" loop).
//
// Strict mode implies diagnostic mode (warning collection). Disabling
// strict mode does NOT disable diagnostic mode — callers control that
// independently.
func (p *Parser) SetStrictMode(enabled bool) {
	p.strictMode = enabled
	if enabled {
		p.diagnosticMode = true
	}
}

// StrictMode reports whether strict mode is active.
func (p *Parser) StrictMode() bool {
	return p.strictMode
}

// strictPromote is called from warn() after a Warning has been
// appended to p.warnings. If strict mode is active and we don't
// already have a sticky error, capture the latest warning as the
// strict error. Subsequent warnings on the same message are still
// recorded (so DiagnosticWarnings() shows the full list) but only the
// first one becomes the returned error — by analogy with how
// io.Reader signals the first error and stops.
func (p *Parser) strictPromote() {
	if !p.strictMode {
		return
	}
	if p.parseErr != nil {
		return
	}
	if len(p.warnings) == 0 {
		return
	}
	p.parseErr = &StrictError{Warning: p.warnings[len(p.warnings)-1]}
}

// takeStrictErr returns and clears the sticky strict error. ParseOne()
// calls this after processing each message; if non-nil, it propagates
// up as the ParseOne return value.
func (p *Parser) takeStrictErr() error {
	if p.parseErr == nil {
		return nil
	}
	err := p.parseErr
	p.parseErr = nil
	return err
}
