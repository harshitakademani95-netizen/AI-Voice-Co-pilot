import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockModeBanner } from '../components/MockModeBanner/MockModeBanner';

describe('MockModeBanner Component', () => {
  it('renders the mock mode banner with clear indicators', () => {
    render(<MockModeBanner />);

    expect(screen.getByRole('region', { name: /mock mode information banner/i })).toBeInTheDocument();
    expect(screen.getByText(/mock mode/i)).toBeInTheDocument();
    expect(screen.getByText(/no paid api keys required/i)).toBeInTheDocument();
    expect(screen.getByText(/gateway: ready/i)).toBeInTheDocument();
  });

  it('toggles configuration options when configure mocks button is clicked', async () => {
    const user = userEvent.setup();
    render(<MockModeBanner />);

    const configBtn = screen.getByRole('button', { name: /configure mocks/i });
    expect(configBtn).toBeInTheDocument();

    await user.click(configBtn);

    expect(screen.getByLabelText(/select simulated network latency/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/simulate api contract error condition/i)).toBeInTheDocument();
  });

  it('triggers error injection callback when error type is selected', async () => {
    const user = userEvent.setup();
    const handleErrorChange = vi.fn();
    render(<MockModeBanner onSimulateErrorChange={handleErrorChange} />);

    await user.click(screen.getByRole('button', { name: /configure mocks/i }));
    const select = screen.getByLabelText(/simulate api contract error condition/i);

    await user.selectOptions(select, 'INVALID_REQUEST');
    expect(handleErrorChange).toHaveBeenCalledWith('INVALID_REQUEST');
    expect(screen.getByText(/error injection active/i)).toBeInTheDocument();
  });
});
