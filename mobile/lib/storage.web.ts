/**
 * Browser storage. localStorage can throw (private mode, blocked storage), so every
 * call is guarded; the app then simply asks the user to sign in again.
 */
export async function getItem(key: string): Promise<string | null> {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export async function setItem(key: string, value: string): Promise<void> {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage unavailable: the session lasts until the tab closes.
  }
}

export async function removeItem(key: string): Promise<void> {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // ignore
  }
}
