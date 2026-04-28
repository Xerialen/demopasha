package parser

import (
	"errors"
	"testing"
)

func TestStrictMode_PromotesWarningToError(t *testing.T) {
	p := &Parser{}
	p.SetStrictMode(true)

	if !p.StrictMode() {
		t.Fatal("StrictMode() should be true after SetStrictMode(true)")
	}
	if !p.diagnosticMode {
		t.Fatal("strict mode must imply diagnostic mode")
	}

	p.warn(1.5, "unknown_svc", "svc_unknown_99 (cmd 99), 12 bytes remaining in payload abandoned")

	err := p.takeStrictErr()
	if err == nil {
		t.Fatal("strict mode should have produced a parseErr after warn()")
	}
	if !errors.Is(err, ErrStrict) {
		t.Fatalf("error should match ErrStrict via errors.Is, got %v", err)
	}

	se, ok := err.(*StrictError)
	if !ok {
		t.Fatalf("expected *StrictError, got %T", err)
	}
	if se.Warning.Type != "unknown_svc" {
		t.Errorf("expected Warning.Type 'unknown_svc', got %q", se.Warning.Type)
	}
	if se.Warning.Time != 1.5 {
		t.Errorf("expected Warning.Time 1.5, got %v", se.Warning.Time)
	}

	if p.parseErr != nil {
		t.Error("takeStrictErr should clear the sticky error")
	}
	if len(p.warnings) != 1 {
		t.Errorf("warnings list should still hold the warning for diagnostic readout, got len=%d", len(p.warnings))
	}
}

func TestStrictMode_FirstWarningWins(t *testing.T) {
	p := &Parser{}
	p.SetStrictMode(true)

	p.warn(1.0, "unknown_svc", "first")
	p.warn(2.0, "unknown_te", "second")

	err := p.takeStrictErr()
	se, ok := err.(*StrictError)
	if !ok {
		t.Fatalf("expected *StrictError, got %T", err)
	}
	if se.Warning.Time != 1.0 {
		t.Errorf("first warning should win, got time=%v", se.Warning.Time)
	}
	if len(p.warnings) != 2 {
		t.Errorf("both warnings should still be recorded, got %d", len(p.warnings))
	}
}

func TestStrictMode_OffIsTransparent(t *testing.T) {
	p := &Parser{}
	p.SetDiagnosticMode(true)

	p.warn(1.0, "unknown_svc", "noise")

	if err := p.takeStrictErr(); err != nil {
		t.Errorf("non-strict diagnostic mode must not produce parseErr, got %v", err)
	}
	if len(p.warnings) != 1 {
		t.Errorf("warning should still be recorded in diagnostic mode, got %d", len(p.warnings))
	}
}

func TestStrictMode_DisableLeavesDiagnostic(t *testing.T) {
	p := &Parser{}
	p.SetStrictMode(true)
	p.SetStrictMode(false)

	if p.StrictMode() {
		t.Error("StrictMode() should be false after SetStrictMode(false)")
	}
	if !p.diagnosticMode {
		t.Error("diagnostic mode should remain on after disabling strict (caller controls it)")
	}
}
