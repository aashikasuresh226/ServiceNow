/** Native builds: email links open in the phone's browser (the web version of the app). */
import { UserError } from './api';
import type { FirebaseConfig } from './types';

export async function finishEmailLink(_config: FirebaseConfig, _email: string): Promise<string> {
  throw new UserError("Open the invite link in your phone's web browser to accept it.");
}
