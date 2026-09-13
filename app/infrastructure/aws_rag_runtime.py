"""AWS clients share the existing request gate; SDK errors never reach the UI."""
from filelock import FileLock, Timeout
from app.application.ports import ExtractionUnavailable


class AwsRagRuntime:
    def __init__(self, transport, clients=None):
        self.transport = transport
        self.clients = clients or {}

    def client(self, service):
        if service not in self.clients:
            import boto3
            from botocore.config import Config
            settings = self.transport.settings
            self.clients[service] = boto3.Session(
                profile_name=settings.aws_profile, region_name=settings.region,
            ).client(service, config=Config(
                retries={'mode': 'standard', 'total_max_attempts': 1},
                connect_timeout=10, read_timeout=120,
            ))
        return self.clients[service]

    def call(self, service, operation, *, consume=None, **kwargs):
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            with FileLock(str(self.transport.repository.data_dir / 'bedrock.lock'), timeout=300):
                if service.startswith('bedrock'):
                    self.transport.gate.wait()
                result = getattr(self.client(service), operation)(**kwargs)
                return consume(result) if consume else result
        except (ClientError, BotoCoreError):
            # Publishing may have succeeded remotely: let explicit sync recover it.
            raise ExtractionUnavailable('AWS 知識庫請求失敗，請確認服務權限、設定或稍後重新查詢。') from None
        except Timeout:
            raise ExtractionUnavailable('其他 AWS 工作正在進行，請稍後重試。') from None
