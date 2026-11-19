/** Homeowner's messages with the shop (and the technician, if their company allows). */
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';

import { ChatThread } from '@/components/ChatThread';
import { Screen, StepHeader, Title } from '@/components/ui';
import { api } from '@/lib/api';
import type { ServiceRequest } from '@/lib/types';

export default function RequestChat() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [request, setRequest] = useState<ServiceRequest | null>(null);
  useEffect(() => { api.getRequest(id).then(setRequest).catch(() => undefined); }, [id]);
  const load = useCallback(() => api.messages(id), [id]);
  const send = useCallback((body: string) => api.sendMessage(id, body), [id]);
  const t = request?.technician;
  const who = t ? (t.can_message ? `${t.first_name} and ${t.shop_name}` : t.shop_name) : 'your HVAC company';
  return (
    <Screen scroll={false}>
      <StepHeader onBack={() => (router.canGoBack() ? router.back() : router.replace(`/request/${id}`))} />
      <Title sub={`Messages with ${who}`}>Messages</Title>
      <ChatThread load={load} send={send} me="homeowner" closed={request ? !request.chat_open : false}
        closedNote="Messages close 48 hours after the job." />
    </Screen>
  );
}
