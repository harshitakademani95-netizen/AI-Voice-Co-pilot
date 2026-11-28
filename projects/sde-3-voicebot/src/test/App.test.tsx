import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../App';

describe('App Component', () => {
  it('renders permission select with prompt, granted, and denied options and shows prompt message when selected', async () => {
    const user = userEvent.setup();
    render(<App />);

    const select = screen.getByLabelText(/demo: set microphone permission/i);
    expect(select).toBeInTheDocument();

    const options = screen.getAllByRole('option');
    const optionValues = options.map((opt) => (opt as HTMLOptionElement).value);
    expect(optionValues).toContain('prompt');
    expect(optionValues).toContain('granted');
    expect(optionValues).toContain('denied');

    // Select "prompt"
    await user.selectOptions(select, 'prompt');

    expect(screen.getByText(/Microphone permission prompt/i)).toBeInTheDocument();
  });
});

