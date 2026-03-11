import { Card, Descriptions, Progress, Tag, Typography } from 'antd';

const { Text } = Typography;

// ── Local types ──

interface InferredType {
  docType: string;
  confidence: number;
  reasoning: string;
}

interface TypeInferenceCardProps {
  inferredType: InferredType;
}

// ── Component ──

export default function TypeInferenceCard({ inferredType }: TypeInferenceCardProps) {
  const percent = Math.round(inferredType.confidence * 100);

  let progressStatus: 'active' | 'exception' | 'normal' = 'normal';
  if (inferredType.confidence > 0.8) {
    progressStatus = 'active';
  } else if (inferredType.confidence < 0.5) {
    progressStatus = 'exception';
  }

  return (
    <div className="animate-fade-in">
      <Card title="🔍 类型推断结果" className="mb-4" size="small">
        <Descriptions column={1} size="small">
          <Descriptions.Item label="推断类型">
            <Tag color="blue" className="text-base px-3 py-0.5">
              {inferredType.docType}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="置信度">
            <Progress
              percent={percent}
              size="small"
              status={progressStatus}
              style={{ maxWidth: 280 }}
            />
          </Descriptions.Item>
          <Descriptions.Item label="推理依据">
            <Text>{inferredType.reasoning}</Text>
          </Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
}
