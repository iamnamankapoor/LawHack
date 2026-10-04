import React from 'react';
import { Composition } from 'remotion';
import { Legible } from './Legible';

export const RemotionRoot: React.FC = () => (
  <Composition id="Legible" component={Legible} durationInFrames={900} fps={30} width={1920} height={1080} />
);
