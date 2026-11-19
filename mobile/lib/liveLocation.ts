/**
 * Shares the technician's position while they drive to ONE job (status en_route).
 * Uses the phone's GPS through expo-location (the browser's geolocation on web).
 * Stops as soon as the screen closes or the job is no longer en route; the server
 * also refuses positions for any other status and deletes them on arrival.
 * (Foreground only: keep the app open while driving.)
 */
import * as Location from 'expo-location';
import { useEffect, useRef, useState } from 'react';

import { techApi } from './api';

const MIN_SEND_INTERVAL_MS = 8000;

export type SharingState = 'off' | 'starting' | 'sharing' | 'denied' | 'error';

export function useLiveLocation(jobId: string, active: boolean) {
  const [state, setState] = useState<SharingState>('off');
  const [lastSent, setLastSent] = useState<Date | null>(null);
  const lastSentAt = useRef(0);

  useEffect(() => {
    if (!active) {
      setState('off');
      return;
    }
    let cancelled = false;
    let subscription: Location.LocationSubscription | null = null;

    const send = async (position: Location.LocationObject, force = false) => {
      const now = Date.now();
      if (!force && now - lastSentAt.current < MIN_SEND_INTERVAL_MS) return;
      lastSentAt.current = now;
      try {
        await techApi.location(jobId, position.coords.latitude, position.coords.longitude,
          position.coords.accuracy);
        if (!cancelled) {
          setState('sharing');
          setLastSent(new Date());
        }
      } catch {
        if (!cancelled) setState('error');
      }
    };

    (async () => {
      setState('starting');
      try {
        const permission = await Location.requestForegroundPermissionsAsync();
        if (permission.status !== 'granted') {
          if (!cancelled) setState('denied');
          return;
        }
        const first = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
        if (cancelled) return;
        await send(first, true);
        subscription = await Location.watchPositionAsync(
          { accuracy: Location.Accuracy.High, timeInterval: 10_000, distanceInterval: 25 },
          (position) => void send(position),
        );
        if (cancelled) subscription.remove();
      } catch {
        if (!cancelled) setState('error');
      }
    })();

    return () => {
      cancelled = true;
      subscription?.remove();
    };
  }, [jobId, active]);

  return { state, lastSent };
}
