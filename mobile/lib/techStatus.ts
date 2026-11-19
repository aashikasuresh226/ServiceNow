/** Status labels in the technician app. */
export const JOB_STATUS: Record<string, [string, 'primary' | 'amber' | 'success' | 'neutral']> = {
  offered: ['New offer', 'amber'],
  dispatched: ['Scheduled', 'primary'],
  en_route: ['Driving', 'primary'],
  on_site: ['On site', 'primary'],
  quoted: ['Waiting for approval', 'amber'],
  in_progress: ['Approved', 'success'],
  completed: ['Done', 'neutral'],
};
