import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Mock @claw/core — provide controllable useAuthStore
const mockLogin = vi.fn<(u: string, p: string) => Promise<boolean>>().mockResolvedValue(true);
let mockLoading = false;
let mockError: string | null = null;

vi.mock('@claw/core', () => ({
  useAuthStore: (selector: (state: Record<string, unknown>) => unknown) => {
    const state = {
      login: mockLogin,
      loading: mockLoading,
      error: mockError,
    };
    return selector(state);
  },
}));

// Dynamic import so the mock is installed first
const loadLoginPage = async () => {
  const mod = await import('../src/LoginPage.tsx');
  return mod.default;
};

describe('LoginPage', () => {
  beforeEach(() => {
    mockLogin.mockClear();
    mockLoading = false;
    mockError = null;
  });

  it('renders login form with username and password inputs', async () => {
    const LoginPage = await loadLoginPage();
    render(<LoginPage />);

    expect(screen.getByLabelText('Username')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    // Exactly 2 inputs
    const inputs = screen.getAllByRole('textbox');
    // password input has no textbox role, count separately
    expect(screen.getByLabelText('Username')).toBeInstanceOf(HTMLInputElement);
    expect(screen.getByLabelText('Password')).toBeInstanceOf(HTMLInputElement);
  });

  it('submit button is disabled when username is empty', async () => {
    const LoginPage = await loadLoginPage();
    render(<LoginPage />);

    const button = screen.getByRole('button', { name: /sign in/i });
    expect(button).toBeDisabled();
  });

  it('calls login on form submit with non-empty username', async () => {
    const LoginPage = await loadLoginPage();
    render(<LoginPage />);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Username'), 'testuser');
    await user.type(screen.getByLabelText('Password'), 'pass123');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('testuser', 'pass123');
    });
  });

  it('displays error message from auth store', async () => {
    mockError = 'Invalid credentials';
    const LoginPage = await loadLoginPage();
    render(<LoginPage />);

    expect(screen.getByText('Invalid credentials')).toBeInTheDocument();
  });

  it('shows loading state during login', async () => {
    mockLoading = true;
    const LoginPage = await loadLoginPage();
    render(<LoginPage />);

    const button = screen.getByRole('button', { name: /signing in/i });
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent('Signing in...');
  });

  it('trims whitespace from username before submit', async () => {
    const LoginPage = await loadLoginPage();
    render(<LoginPage />);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Username'), '  user  ');
    await user.type(screen.getByLabelText('Password'), 'pw');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('user', 'pw');
    });
  });
});
