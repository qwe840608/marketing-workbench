import test from 'node:test';
import assert from 'node:assert/strict';
import { audiencePlatforms, audienceSections, itemLabel, peakHours, platformNotes, sectionTitle, shares, unavailableText } from '../src/audience.ts';

test('受眾占比：人數換成百分比，平台給的百分比原樣使用，合計 0 不出現 NaN', () => {
  assert.deepEqual(shares([{ key: 'F', value: 3 }, { key: 'M', value: 1 }], 'count').map(row => row.share), [75, 25]);
  assert.deepEqual(shares([{ key: '18-24', value: 12.5 }], 'percent').map(row => row.share), [12.5]);
  assert.deepEqual(shares([{ key: 'TW', value: 0 }], 'count').map(row => row.share), [0]);
});

test('上線高峰：取人數最多的三個時段，依時間排列；全部為 0 時沒有高峰', () => {
  const hours = Array.from({ length: 24 }, (_, hour) => ({ key: String(hour), value: [20, 21, 9].includes(hour) ? 50 + hour : 1 }));
  assert.deepEqual(peakHours(hours), [9, 20, 21]);
  assert.deepEqual(peakHours(hours.map(row => ({ ...row, value: 0 }))), []);
});

test('受眾標籤：性別代碼、YouTube 的 65-、國家代碼與時段', () => {
  assert.equal(itemLabel('gender', 'F'), '女性');
  assert.equal(itemLabel('gender', 'male'), '男性');
  assert.equal(itemLabel('gender', 'user_specified'), '未指定');
  assert.equal(itemLabel('age', '65-'), '65+');
  assert.equal(itemLabel('age', '18-24'), '18-24');
  assert.notEqual(itemLabel('country', 'TW'), '');
  assert.equal(itemLabel('country', 'not-a-code'), 'not-a-code');
  assert.equal(itemLabel('city', 'Taipei, Taiwan'), 'Taipei, Taiwan');
  assert.equal(itemLabel('hour', '9'), '9 時');
});

test('六個平台都有說明；沒有官方資料的 TikTok、LINE 只顯示原因', () => {
  assert.deepEqual([...audiencePlatforms], ['instagram', 'facebook', 'threads', 'youtube', 'tiktok', 'line']);
  for (const platform of audiencePlatforms) {
    assert.ok(platformNotes(platform).length > 0, platform);
    for (const section of audienceSections[platform]) assert.ok(sectionTitle(section), `${platform} ${section.breakdown}`);
  }
  assert.deepEqual(audienceSections.tiktok, []);
  assert.deepEqual(audienceSections.line, []);
  assert.ok(!audienceSections.facebook.some(section => section.breakdown === 'age' || section.breakdown === 'gender'));
  assert.match(platformNotes('tiktok')[0], /Business API/);
});

test('缺資料的提示依原因給出可以採取的行動', () => {
  assert.match(unavailableText('permission_missing'), /重新連結/);
  assert.match(unavailableText('not_available'), /100/);
  assert.match(unavailableText(null), /沒有回傳資料/);
});
