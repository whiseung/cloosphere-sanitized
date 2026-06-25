#!/usr/bin/env python3
"""
Cloosphere 라이선스 키 생성 CLI

RSA 개인키로 라이선스 키(tier) 또는 기능 키(feature)를 생성합니다.
생성된 키를 관리자 설정 > License 탭에서 등록하면 됩니다.

사용법:
    # 개인키 생성 (최초 1회)
    python generate_license_key.py init

    # 라이선스 키 생성
    python generate_license_key.py license --tier standard --company "고객사" --max-users 50 --expires 2027-01-01

    # 기능 키 생성
    python generate_license_key.py feature --module kbsphere --company "고객사" --expires 2027-01-01

    # 사용 가능한 모듈 목록 확인
    python generate_license_key.py modules
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    print("필요한 패키지를 설치하세요:")
    print("  pip install PyJWT cryptography")
    sys.exit(1)

ALGORITHM = "RS256"
ISSUER = "cloosphere"

VALID_TIERS = ["basic", "standard", "professional"]
VALID_MODULES = [
    "kbsphere",
    "dbsphere",
    "guardrail",
    "agent_flow",
    "auto_evaluation",
    "unified_agent",
]

TIER_MODULES = {
    "basic": [],
    "standard": ["kbsphere", "dbsphere", "guardrail"],
    "professional": [
        "kbsphere",
        "dbsphere",
        "guardrail",
        "agent_flow",
        "auto_evaluation",
        "unified_agent",
    ],
}

DEFAULT_KEY_DIR = Path(__file__).parent / ".license_keys"


def get_private_key_path() -> Path:
    return DEFAULT_KEY_DIR / "private_key.pem"


def get_public_key_path() -> Path:
    return DEFAULT_KEY_DIR / "public_key.pem"


def cmd_init(args):
    """RSA 키쌍을 생성합니다."""
    DEFAULT_KEY_DIR.mkdir(parents=True, exist_ok=True)

    private_path = get_private_key_path()
    public_path = get_public_key_path()

    if private_path.exists() and not args.force:
        print(f"이미 키가 존재합니다: {private_path}")
        print("덮어쓰려면 --force 옵션을 사용하세요.")
        sys.exit(1)

    # RSA 2048 키쌍 생성
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # 개인키 저장
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_path.write_bytes(private_pem)

    # 공개키 저장
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_path.write_bytes(public_pem)

    print("키쌍 생성 완료:")
    print(f"  개인키: {private_path}")
    print(f"  공개키: {public_path}")
    print()
    print("공개키를 backend/open_webui/utils/license.py의")
    print("CLOOSPHERE_PUBLIC_KEY에 붙여넣으세요:")
    print()
    print(public_pem.decode())


def load_private_key() -> str:
    """개인키 PEM을 로드합니다."""
    private_path = get_private_key_path()
    if not private_path.exists():
        print(f"개인키를 찾을 수 없습니다: {private_path}")
        print("먼저 'init' 명령으로 키를 생성하세요.")
        sys.exit(1)
    return private_path.read_text()


def parse_expires(expires_str: str) -> int:
    """만료일 문자열을 Unix timestamp로 변환합니다."""
    try:
        dt = datetime.strptime(expires_str, "%Y-%m-%d")
        dt = dt.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        print(f"잘못된 날짜 형식: {expires_str} (YYYY-MM-DD 형식을 사용하세요)")
        sys.exit(1)


def cmd_license(args):
    """라이선스 키를 생성합니다."""
    if args.tier not in VALID_TIERS:
        print(f"잘못된 티어: {args.tier}")
        print(f"사용 가능한 티어: {', '.join(VALID_TIERS)}")
        sys.exit(1)

    private_key = load_private_key()
    now = int(time.time())
    exp = parse_expires(args.expires)

    payload = {
        "iss": ISSUER,
        "type": "license",
        "tier": args.tier,
        "company": args.company,
        "max_users": args.max_users,
        "exp": exp,
        "iat": now,
    }

    token = jwt.encode(payload, private_key, algorithm=ALGORITHM)

    print("=== 라이선스 키 생성 완료 ===")
    print(f"  티어: {args.tier}")
    print(f"  회사: {args.company}")
    print(f"  최대 사용자: {args.max_users or '무제한'}")
    print(f"  만료일: {args.expires}")
    print(f"  포함 모듈: {', '.join(TIER_MODULES[args.tier]) or '없음'}")
    print()
    print("키:")
    print(token)


def cmd_feature(args):
    """기능 키를 생성합니다."""
    if args.module not in VALID_MODULES:
        print(f"잘못된 모듈: {args.module}")
        print(f"사용 가능한 모듈: {', '.join(VALID_MODULES)}")
        sys.exit(1)

    private_key = load_private_key()
    now = int(time.time())
    exp = parse_expires(args.expires)

    payload = {
        "iss": ISSUER,
        "type": "feature",
        "module": args.module,
        "company": args.company,
        "exp": exp,
        "iat": now,
    }

    token = jwt.encode(payload, private_key, algorithm=ALGORITHM)

    print("=== 기능 키 생성 완료 ===")
    print(f"  모듈: {args.module}")
    print(f"  회사: {args.company}")
    print(f"  만료일: {args.expires}")
    print()
    print("키:")
    print(token)


def cmd_modules(_args):
    """사용 가능한 모듈과 티어 매핑을 출력합니다."""
    print("=== 티어별 포함 모듈 ===")
    print()
    header = f"  {'모듈':<20} {'Basic':^8} {'Standard':^10} {'Professional':^14}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for module in VALID_MODULES:
        basic = "O" if module in TIER_MODULES["basic"] else ""
        standard = "O" if module in TIER_MODULES["standard"] else ""
        professional = "O" if module in TIER_MODULES["professional"] else ""
        print(f"  {module:<20} {basic:^8} {standard:^10} {professional:^14}")
    print()
    print("기능 키로 개별 모듈을 추가 활성화할 수 있습니다.")


def cmd_verify(args):
    """키를 검증하고 내용을 출력합니다."""
    public_path = get_public_key_path()
    if not public_path.exists():
        print(f"공개키를 찾을 수 없습니다: {public_path}")
        sys.exit(1)

    public_key = public_path.read_text()
    token = args.key

    try:
        payload = jwt.decode(token, public_key, algorithms=[ALGORITHM], issuer=ISSUER)
        print("=== 키 검증 성공 ===")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    except jwt.ExpiredSignatureError:
        print("키가 만료되었습니다.")
    except jwt.InvalidSignatureError:
        print("서명이 유효하지 않습니다.")
    except jwt.DecodeError as e:
        print(f"디코딩 실패: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Cloosphere 라이선스 키 생성 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s init                                          # 키쌍 생성
  %(prog)s license -t standard -c "고객사" -e 2027-01-01  # 라이선스 키
  %(prog)s feature -m kbsphere -c "고객사" -e 2027-01-01  # 기능 키
  %(prog)s modules                                       # 모듈 목록
  %(prog)s verify <JWT_TOKEN>                            # 키 검증
""",
    )
    subparsers = parser.add_subparsers(dest="command", help="명령어")

    # init
    init_parser = subparsers.add_parser("init", help="RSA 키쌍 생성")
    init_parser.add_argument("--force", action="store_true", help="기존 키 덮어쓰기")

    # license
    license_parser = subparsers.add_parser("license", help="라이선스 키 생성")
    license_parser.add_argument(
        "-t", "--tier", required=True, choices=VALID_TIERS, help="라이선스 티어"
    )
    license_parser.add_argument("-c", "--company", required=True, help="회사명")
    license_parser.add_argument(
        "-u", "--max-users", type=int, default=0, help="최대 사용자 수 (0=무제한)"
    )
    license_parser.add_argument(
        "-e", "--expires", required=True, help="만료일 (YYYY-MM-DD)"
    )

    # feature
    feature_parser = subparsers.add_parser("feature", help="기능 키 생성")
    feature_parser.add_argument(
        "-m", "--module", required=True, choices=VALID_MODULES, help="모듈명"
    )
    feature_parser.add_argument("-c", "--company", required=True, help="회사명")
    feature_parser.add_argument(
        "-e", "--expires", required=True, help="만료일 (YYYY-MM-DD)"
    )

    # modules
    subparsers.add_parser("modules", help="모듈 및 티어 매핑 확인")

    # verify
    verify_parser = subparsers.add_parser("verify", help="키 검증")
    verify_parser.add_argument("key", help="검증할 JWT 키")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "init": cmd_init,
        "license": cmd_license,
        "feature": cmd_feature,
        "modules": cmd_modules,
        "verify": cmd_verify,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
