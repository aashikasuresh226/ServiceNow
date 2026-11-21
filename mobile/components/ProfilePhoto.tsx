/** A profile photo with "Change photo" (library) and "Remove". */
import * as ImagePicker from 'expo-image-picker';
import { View } from 'react-native';

import { Avatar } from './illustrations';
import { Button, ErrorText, Muted, Row } from './ui';
import { useAction } from '@/lib/hooks';

export function ProfilePhoto({ uri, name, hint, onPick, onRemove }: {
  uri: string | null | undefined;
  name?: string | null;
  hint?: string;
  onPick: (uri: string, mimeType?: string) => Promise<unknown>;
  onRemove: () => Promise<unknown>;
}) {
  const pick = useAction(async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'], allowsEditing: true, aspect: [1, 1], quality: 0.85,
    });
    if (result.canceled || !result.assets?.[0]) return;
    await onPick(result.assets[0].uri, result.assets[0].mimeType ?? undefined);
  });
  const remove = useAction(onRemove);
  return (
    <View style={{ gap: 8 }}>
      <Row style={{ gap: 14 }}>
        <Avatar size={72} name={name ?? undefined} uri={uri} />
        <View style={{ flex: 1, gap: 8 }}>
          <Button label={uri ? 'Change photo' : 'Add a photo'} variant="secondary" icon="camera"
            busy={pick.busy} onPress={() => pick.run()} />
          {uri ? <Button label="Remove photo" variant="danger" busy={remove.busy} onPress={() => remove.run()} /> : null}
        </View>
      </Row>
      {hint ? <Muted>{hint}</Muted> : null}
      <ErrorText message={pick.error ?? remove.error} />
    </View>
  );
}
