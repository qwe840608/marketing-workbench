import { type GuideContext, type GuideId, platformGuides } from '../platformGuides';
import { GuideDialog } from './GuideDialog';

// 教學內容較大，由平台連線頁以 lazy() 載入，按「設定教學」時才下載。
export default function GuideModal({ id, context, onClose }: { id: GuideId; context: GuideContext; onClose: () => void }) {
  return <GuideDialog guide={platformGuides[id]} context={context} onClose={onClose} />;
}
