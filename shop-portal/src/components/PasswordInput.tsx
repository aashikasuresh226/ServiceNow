/** A password field with an eye button: shows what was typed, and hides it again. */
import { useState } from 'react';
import type { InputHTMLAttributes } from 'react';

import { Icon } from './Icon';

export function PasswordInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, 'type'>) {
  const [shown, setShown] = useState(false);
  return (
    <div className="password-field">
      <input {...props} className="input" type={shown ? 'text' : 'password'}
        autoCapitalize="off" autoCorrect="off" spellCheck={false} />
      <button type="button" className="password-eye" onClick={() => setShown(!shown)}
        aria-label={shown ? 'Hide password' : 'Show password'} aria-pressed={shown}
        aria-controls={props.id} title={shown ? 'Hide password' : 'Show password'}>
        <Icon name={shown ? 'eye-off' : 'eye'} size={18} />
      </button>
    </div>
  );
}
