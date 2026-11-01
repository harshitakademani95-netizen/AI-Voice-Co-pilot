import React, { useState } from 'react';
import { Presentation, Play, FastForward, RotateCcw } from 'lucide-react';
import { TimelineEvent } from '../../api/types';
import { INITIAL_FIXTURE_EVENTS } from '../../fixtures/mockTimelineEvents';
import './DemoRunner.css';

interface DemoRunnerProps {
  onLoadEvents: (events: TimelineEvent[]) => void;
  onAddEvent: (event: TimelineEvent) => void;
  onClearEvents: () => void;
  onSimulateVoiceSpeaking: () => void;
}

export const DemoRunner: React.FC<DemoRunnerProps> = ({
  onLoadEvents,
  onAddEvent,
  onClearEvents,
  onSimulateVoiceSpeaking,
}) => {
  const [currentStep, setCurrentStep] = useState<number>(INITIAL_FIXTURE_EVENTS.length);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);

  const resetToStepZero = () => {
    setIsPlaying(false);
    setCurrentStep(0);
    onClearEvents();
  };

  const loadFullDemo = () => {
    setIsPlaying(false);
    setCurrentStep(INITIAL_FIXTURE_EVENTS.length);
    onLoadEvents(INITIAL_FIXTURE_EVENTS);
  };

  const advanceNextStep = () => {
    if (currentStep < INITIAL_FIXTURE_EVENTS.length) {
      const nextEvent = INITIAL_FIXTURE_EVENTS[currentStep];
      onAddEvent(nextEvent);
      setCurrentStep((prev) => prev + 1);

      if (nextEvent.type === 'voice_output') {
        onSimulateVoiceSpeaking();
      }
    }
  };

  const autoplayDemo = async () => {
    setIsPlaying(true);
    let step = currentStep >= INITIAL_FIXTURE_EVENTS.length ? 0 : currentStep;
    if (step === 0) {
      onClearEvents();
    }

    while (step < INITIAL_FIXTURE_EVENTS.length) {
      const nextEvt = INITIAL_FIXTURE_EVENTS[step];
      onAddEvent(nextEvt);
      if (nextEvt.type === 'voice_output') {
        onSimulateVoiceSpeaking();
      }
      step++;
      setCurrentStep(step);
      // Wait between steps
      await new Promise((r) => setTimeout(r, 900));
    }
    setIsPlaying(false);
  };

  return (
    <section className="demo-card" aria-labelledby="demo-runner-heading">
      <div className="demo-header">
        <div className="demo-title-wrap">
          <Presentation size={18} color="#818cf8" aria-hidden="true" />
          <h2 id="demo-runner-heading" className="demo-title">
            Day 7 Interactive Demo
          </h2>
        </div>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          Step {currentStep} of {INITIAL_FIXTURE_EVENTS.length}
        </span>
      </div>

      <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
        Demonstrate the Week 1 vertical slice: voice capture, context correlation, LLM reasoning, agent plan, safety approval, and TTS response.
      </p>

      <div className="demo-progress-bar" role="progressbar" aria-valuenow={currentStep} aria-valuemin={0} aria-valuemax={INITIAL_FIXTURE_EVENTS.length}>
        <div
          className="demo-progress-fill"
          style={{ width: `${(currentStep / INITIAL_FIXTURE_EVENTS.length) * 100}%` }}
        />
      </div>

      <div className="demo-actions" role="toolbar" aria-label="Demo controls">
        <button
          type="button"
          className="btn-demo btn-demo-primary"
          onClick={advanceNextStep}
          disabled={isPlaying || currentStep >= INITIAL_FIXTURE_EVENTS.length}
          aria-label="Advance next demo step"
        >
          <FastForward size={14} aria-hidden="true" />
          <span>Next Step</span>
        </button>

        <button
          type="button"
          className="btn-demo btn-demo-secondary"
          onClick={autoplayDemo}
          disabled={isPlaying}
          aria-label="Autoplay full demonstration"
        >
          <Play size={14} aria-hidden="true" />
          <span>{isPlaying ? 'Playing...' : 'Autoplay Demo'}</span>
        </button>

        <button
          type="button"
          className="btn-demo btn-demo-secondary"
          onClick={loadFullDemo}
          disabled={isPlaying}
          aria-label="Load complete fixture scenario"
        >
          <span>Load All</span>
        </button>

        <button
          type="button"
          className="btn-demo btn-demo-secondary"
          onClick={resetToStepZero}
          disabled={isPlaying}
          aria-label="Reset demo steps"
        >
          <RotateCcw size={13} aria-hidden="true" />
          <span>Reset</span>
        </button>
      </div>
    </section>
  );
};
