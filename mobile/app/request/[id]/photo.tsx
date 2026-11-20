import * as ImagePicker from 'expo-image-picker';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Platform, Pressable, StyleSheet, Text, View } from 'react-native';

import { Icon } from '@/components/icons';
import { Viewfinder } from '@/components/illustrations';
import { colors } from '@/components/theme';
import { Button, ErrorText, Muted, Row, Screen, StepHeader, TextLink, Title } from '@/components/ui';
import { api, UserError } from '@/lib/api';
import { useAction, useOptions } from '@/lib/hooks';
import type { ServiceRequest } from '@/lib/types';

const ANALYSIS_STEPS = ['Reading the data plate', 'Identifying your unit', 'Checking likely causes',
  'Estimating cost'];

export default function Photo() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const aiOn = useOptions()?.features.photo_analysis ?? false;
  const [request, setRequest] = useState<ServiceRequest | null>(null);
  const [analysisStep, setAnalysisStep] = useState(0);

  useEffect(() => {
    api.getRequest(id).then(setRequest).catch(() => undefined);
  }, [id]);

  const upload = useAction(async (source: 'camera' | 'library') => {
    const pickerOptions: ImagePicker.ImagePickerOptions = {
      mediaTypes: ['images'], quality: 0.7, allowsEditing: false,
    };
    if (source === 'camera' && Platform.OS !== 'web') {
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) throw new UserError('Camera permission is needed to take a photo');
    }
    const result = source === 'camera' && Platform.OS !== 'web'
      ? await ImagePicker.launchCameraAsync(pickerOptions)
      : await ImagePicker.launchImageLibraryAsync(pickerOptions);
    const asset = result.canceled ? undefined : result.assets[0];
    if (!asset) return;
    setRequest(await api.uploadPhoto(id, asset.uri, asset.mimeType ?? 'image/jpeg'));
  });

  const analyze = useAction(async () => {
    setAnalysisStep(0);
    const timer = setInterval(() => setAnalysisStep((s) => Math.min(s + 1, ANALYSIS_STEPS.length - 1)), 900);
    try {
      await api.analyze(id);
      router.replace(`/request/${id}/diagnosis`);
    } finally {
      clearInterval(timer);
    }
  });

  if (analyze.busy) {
    return (
      <Screen scroll={false}>
        <View style={styles.analyzing}>
          <View style={styles.sparkle}><Icon name="sparkle" size={36} color={colors.primary} /></View>
          <Title>Analyzing your unit…</Title>
          <View style={{ gap: 10, alignSelf: 'stretch', paddingHorizontal: 16 }}>
            {ANALYSIS_STEPS.map((label, i) => (
              <Row key={label}>
                {i < analysisStep ? <Icon name="check" size={18} color={colors.primary} strokeWidth={3} />
                  : i === analysisStep ? <ActivityIndicator size="small" color={colors.primary} />
                    : <View style={{ width: 18 }} />}
                <Text style={{ color: i <= analysisStep ? colors.ink : colors.faint, fontSize: 15 }}>{label}</Text>
              </Row>
            ))}
          </View>
          <Muted style={{ textAlign: 'center' }}>Usually under 15 seconds. If it takes too long, we'll continue and your technician will check on site.</Muted>
        </View>
      </Screen>
    );
  }

  const photos = request?.photos ?? [];
  return (
    <Screen footer={
      <>
        <Button label={photos.length ? (aiOn ? 'Analyze my unit' : 'Continue') : 'Take photo'}
          icon={photos.length ? 'sparkle' : 'camera'} busy={upload.busy}
          onPress={() => (photos.length ? analyze.run() : upload.run('camera'))} />
        {!photos.length ? (
          <TextLink label={request?.description?.trim() ? 'Skip photo, use my description' : 'Skip photo'} color={colors.muted}
            onPress={() => analyze.run()} />
        ) : null}
      </>
    }>
      <StepHeader step={2} />
      <Title sub="Show the label with the model and serial number if you can.">Snap your unit</Title>
      <Muted style={{ fontSize: 12 }}>
        Photos and the repair details are kept to improve our diagnoses (location data is removed; never shared with your name or address).
      </Muted>
      <View style={styles.viewfinder}><Viewfinder width={230} /></View>
      <Row style={{ gap: 8 }}>
        {photos.map((p) => (
          <View key={p.id} style={styles.thumb}>
            <Image source={{ uri: p.url }} style={styles.thumbImage} accessibilityLabel="Uploaded photo" />
            <View style={styles.thumbCheck}><Icon name="check" size={10} color="#FFF" strokeWidth={4} /></View>
          </View>
        ))}
        {photos.length < 5 ? (
          <Pressable style={[styles.thumb, styles.addThumb]} onPress={() => upload.run('library')}
            accessibilityRole="button" accessibilityLabel="Add a photo from your library">
            {upload.busy ? <ActivityIndicator color={colors.primary} />
              : <Icon name={photos.length ? 'plus' : 'image'} size={22} color={colors.muted} />}
          </Pressable>
        ) : null}
      </Row>
      <Muted>Indoor or outdoor unit both work. Up to 5 photos.</Muted>
      {aiOn ? (
        <Muted>AI reads the label (brand, model, serial, age, refrigerant) and looks for visible problems.</Muted>
      ) : (
        <Muted>Photo analysis isn't switched on yet. Your photos are shared with your technician.</Muted>
      )}
      <ErrorText message={upload.error ?? analyze.error} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  viewfinder: { backgroundColor: '#2B3140', borderRadius: 16, alignItems: 'center', paddingVertical: 14 },
  thumb: { width: 64, height: 64, borderRadius: 10, overflow: 'hidden', backgroundColor: colors.line },
  thumbImage: { width: '100%', height: '100%' },
  thumbCheck: {
    position: 'absolute', right: 4, top: 4, width: 16, height: 16, borderRadius: 8,
    backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center',
  },
  addThumb: {
    backgroundColor: colors.surface, borderWidth: 1.5, borderStyle: 'dashed',
    borderColor: colors.lineStrong, alignItems: 'center', justifyContent: 'center',
  },
  analyzing: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 22 },
  sparkle: {
    width: 76, height: 76, borderRadius: 38, backgroundColor: colors.primarySoft,
    alignItems: 'center', justifyContent: 'center',
  },
});
