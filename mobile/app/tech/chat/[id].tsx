/** Technician's messages with the customer (only if their company allows it). */
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';

import { ChatThread } from '@/components/ChatThread';
import { Screen, StepHeader, Title } from '@/components/ui';
import { techApi } from '@/lib/api';
import type { TechJob } from '@/lib/types';

export default function TechChat() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [job, setJob] = useState<TechJob | null>(null);
  useEffect(() => { techApi.job(id).then(setJob).catch(() => undefined); }, [id]);
  const load = useCallback(() => techApi.messages(id), [id]);
  const send = useCallback((body: string) => techApi.sendMessage(id, body), [id]);
  return (
    <Screen scroll={false}>
      <StepHeader onBack={() => (router.canGoBack() ? router.back() : router.replace(`/tech/job/${id}`))} />
      <Title sub="Your office sees these messages too.">{job?.customer_name ?? 'Customer'}</Title>
      <ChatThread load={load} send={send} me="technician" closed={job ? !job.chat_open : false}
        closedNote="Messages close 48 hours after the job." />
    </Screen>
  );
}
