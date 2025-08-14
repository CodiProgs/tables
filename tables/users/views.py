import json
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from fido2.server import Fido2Server
from fido2.webauthn import PublicKeyCredentialRpEntity, AuthenticationResponse
from django.contrib.auth import get_user_model
from .models import WebAuthnCredential
from django.contrib.auth import login
import base64
from fido2.webauthn import PublicKeyCredentialUserEntity
from fido2.cose import CoseKey
import cbor2


rp = PublicKeyCredentialRpEntity(name="Бизнес таблицы", id="localhost")
server = Fido2Server(rp)

User = get_user_model()

def ensure_bytes(data):
    if data is None:
        return b''
    
    if isinstance(data, bytes):
        return data
    
    if isinstance(data, memoryview):
        return bytes(data)
    
    if isinstance(data, str):
        try:
            if all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=' for c in data):
                padding = 4 - (len(data) % 4)
                if padding < 4:
                    data += '=' * padding
                
                try:
                    return base64.urlsafe_b64decode(data)
                except:
                    pass
            
            if len(data) % 4 == 0 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in data):
                try:
                    return base64.b64decode(data)
                except:
                    pass
                    
            return bytes(data, 'utf-8')
        except Exception as e:
            print(f"Error converting string to bytes: {str(e)}")
            return bytes(data, 'utf-8')
    
    try:
        return bytes(data)
    except:
        try:
            return bytes(str(data), 'utf-8')
        except Exception as e:
            print(f"Critical error converting to bytes: {str(e)}")
            return b''

def get_webauthn_server(request):
    hostname = request.get_host()
    domain = hostname.split(':')[0]
    if domain == 'localhost' or domain == '127.0.0.1':
        domain = 'localhost'
    
    rp = PublicKeyCredentialRpEntity(name="YourSiteName", id=domain)
    return Fido2Server(rp), rp

class WebAuthnJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode('utf-8')
        return super().default(obj)

@csrf_exempt
def register_options(request):
    try:
        data = json.loads(request.body)
        username = data.get("username")
        password = data.get("password")

        if not username:
            return JsonResponse({"status": "error", "message": "Не указано имя"}, status=400)
        if not password:
            return JsonResponse({"status": "error", "message": "Не указан пароль"}, status=400)

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Пользователь не найден"}, status=400)

        if user.password != password:
            return JsonResponse({"status": "error", "message": "Неверный пароль"}, status=400)

        if user.webauthn_credentials.exists():
            return JsonResponse({"status": "error", "message": "Пользователь уже зарегистрирован"}, status=400)

        server, rp = get_webauthn_server(request)

        user_id = user.id.to_bytes(8, "big")

        credentials_objects = list(user.webauthn_credentials.all())

        credentials = []
        for cred in credentials_objects:
            try:
                cred_id = ensure_bytes(cred.credential_id)
                credentials.append({
                    "type": "public-key",
                    "id": cred_id,
                })
            except Exception:
                pass

        user_entity = PublicKeyCredentialUserEntity(
            id=user_id,
            name=username,
            display_name=username,
        )

        registration_data, state = server.register_begin(
            user_entity,
            credentials=credentials,
            user_verification="preferred"
        )

        challenge = state["challenge"]
        challenge_bytes = ensure_bytes(challenge) if isinstance(challenge, str) else challenge
        challenge_base64 = base64.urlsafe_b64encode(challenge_bytes).decode("utf-8").rstrip("=")

        request.session["state"] = {
            "challenge_base64": base64.b64encode(challenge_bytes).decode("utf-8"),
            "user_verification": state.get("user_verification", "preferred"),
        }
        request.session["user_id"] = user.id

        response_data = {
            "publicKey": {
                "rp": {
                    "name": rp.name,
                    "id": rp.id,
                },
                "user": {
                    "id": base64.b64encode(user_id).decode("utf-8"),
                    "name": username,
                    "displayName": username,
                },
                "challenge": challenge_base64,
                "pubKeyCredParams": [
                    {"type": "public-key", "alg": -7},
                    {"type": "public-key", "alg": -257},
                ],
                "timeout": 60000,
                "excludeCredentials": [{
                    "type": "public-key",
                    "id": base64.b64encode(ensure_bytes(cred.credential_id)).decode("utf-8"),
                    "transports": ["usb", "nfc", "ble", "internal"],
                } for cred in credentials_objects],
                "authenticatorSelection": {
                    "userVerification": "preferred",
                    "requireResidentKey": False,
                    "authenticatorAttachment": "platform",
                },
                "attestation": "none",
            }
        }

        return JsonResponse(response_data)

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

def serialize_public_key(pub_key):
    try:
        key_data = pub_key
        return cbor2.dumps(key_data)
    except AttributeError as e:
        raise ValueError(f"Cannot access _raw_key of public_key: {e}")

def convert_to_bytes(data):
    if data is None:
        return b''
    
    if isinstance(data, bytes):
        return data
    
    if isinstance(data, memoryview):
        return bytes(data)
    
    if isinstance(data, str):
        try:
            return data.encode('utf-8')
        except:
            pass
    
    if hasattr(data, '__bytes__'):
        try:
            return bytes(data)
        except:
            pass
    
    if hasattr(data, '__dict__'):
        try:
            return json.dumps(data.__dict__).encode('utf-8')
        except:
            pass
    
    if isinstance(data, (list, dict)):
        try:
            return json.dumps(data).encode('utf-8')
        except:
            pass
    
    try:
        return str(data).encode('utf-8')
    except:
        return b''

@csrf_exempt
def register_complete(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST allowed")

    try:
        data = json.loads(request.body)
        state = request.session.get("state")
        user_id = request.session.get("user_id")
        
        if not state or not user_id:
            return HttpResponseBadRequest("Session expired")

        if 'challenge_base64' in state:
            challenge_bytes = base64.b64decode(state['challenge_base64'])
            print(f"Restored challenge from session, length: {len(challenge_bytes)}")
            
            challenge_urlsafe = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8')
            
            state = {
                'challenge': challenge_urlsafe,
                'user_verification': state.get('user_verification', 'preferred')
            }
        else:
            print("Warning: No challenge_base64 in state!")
            return HttpResponseBadRequest("Invalid session state")
        
        user = User.objects.get(id=user_id)
        server, _ = get_webauthn_server(request)
        
        client_data_json = ensure_bytes(data["clientDataJSON"])
        attestation_object = ensure_bytes(data["attestationObject"])
        
        raw_id = None
        if "rawId" in data:
            raw_id = ensure_bytes(data["rawId"])
        elif "id" in data:
            raw_id = ensure_bytes(data["id"])
        
        if not raw_id:
            return HttpResponseBadRequest("Missing rawId or id in request")
        
        response_obj = {
            "rawId": raw_id,
            "id": raw_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": client_data_json,
                "attestationObject": attestation_object
            }
        }
        
        print(f"Sending to server.register_complete - challenge format: {type(state['challenge'])}")
        auth_data = server.register_complete(state, response_obj)

        print(f"auth_data type: {type(auth_data)}")
        print(f"auth_data attributes: {dir(auth_data)}")
        
        if hasattr(auth_data, 'credential_data'):
            try:
                credential = auth_data.credential_data
                
                if hasattr(credential, 'credential_id'):
                    cred_id = credential.credential_id
                    if not isinstance(cred_id, bytes):
                        cred_id = bytes(cred_id)
                else:
                    cred_id = raw_id
                
                if hasattr(credential, 'public_key'):
                    pub_key = credential.public_key
                    print(f"Public key type: {pub_key}")
                    try:
                        pub_key_bytes = serialize_public_key(pub_key)

                    except Exception as e:
                        print(f"Error serializing public_key: {str(e)}")
                        raise ValueError("public_key object cannot be serialized to bytes")
                else:
                    raise ValueError("No public_key found in credential data")
                
                sign_count = 0
                if hasattr(auth_data, 'counter'):
                    sign_count = auth_data.counter
                
                WebAuthnCredential.objects.create(
                    user=user,
                    credential_id=cred_id,
                    public_key=pub_key_bytes,
                    sign_count=sign_count
                )
                
                print(f"Credential saved successfully: id={cred_id[:10]}...")
                
            except Exception as e:
                print(f"Error while processing credential data: {str(e)}")
                print(f"Trying alternative method...")
                raise
        
        if not hasattr(auth_data, 'credential_data') or 'Error while processing credential data' in locals():
            print("Using alternative method to extract credential data")
            
            if not isinstance(raw_id, bytes):
                print(f"Converting raw_id to bytes, type: {type(raw_id)}")
                raw_id = bytes(raw_id)
            
            if hasattr(auth_data, 'credential_data') and hasattr(auth_data.credential_data, 'public_key'):
                public_key_data = auth_data.credential_data.public_key
                if not isinstance(public_key_data, bytes):
                    print(f"Converting public_key_data to bytes, type: {type(public_key_data)}")
                    try:
                        if hasattr(public_key_data, '__dict__'):
                            public_key_data = json.dumps(public_key_data.__dict__).encode('utf-8')
                        else:
                            public_key_data = bytes(public_key_data)
                    except Exception as e:
                        print(f"Error converting public_key_data: {str(e)}")
                        public_key_data = b''
            else:
                print("Could not find public_key in auth_data.credential_data")
                public_key_data = b''
            
            WebAuthnCredential.objects.create(
                user=user,
                credential_id=raw_id,
                public_key=public_key_data,
                sign_count=0
            )
            
            print(f"Credential saved successfully with alternative method: id={raw_id[:10]}...")
            
        return JsonResponse({"status": "ok"})
    except Exception as e:
        import traceback
        print(f"Error in register_complete: {str(e)}")
        print(traceback.format_exc())
        return HttpResponseBadRequest(f"Server error: {str(e)}")

def base64url_to_bytes(base64url):
    padding = 4 - (len(base64url) % 4)
    if padding < 4:
        base64url += '=' * padding
    
    return base64.urlsafe_b64decode(base64url)

@csrf_exempt
def authenticate_options(request):
    try:
        data = json.loads(request.body)
        username = data.get("username")
        credential_id_b64 = data.get("credentialId")

        if not username and not credential_id_b64:
            return JsonResponse(
                {"status": "error", "message": "Требуется имя пользователя"},
                status=400,
            )

        user = None

        if username:
            user = User.objects.filter(username=username).first()
            if not user:
                return JsonResponse(
                    {"status": "error", "message": "Пользователь не найден"},
                    status=400,
                )
        else:
            try:
                padded_cred = credential_id_b64 + "=" * (-len(credential_id_b64) % 4)
                cred_id_bytes = base64.b64decode(padded_cred)
            except Exception:
                return JsonResponse(
                    {"status": "error", "message": "Некорректный credentialId"},
                    status=400,
                )

            cred = WebAuthnCredential.objects.filter(credential_id=cred_id_bytes).first()
            if not cred:
                return JsonResponse(
                    {"status": "error", "message": "Пользователь с таким отпечатком не найден"},
                    status=400,
                )
            user = cred.user

        server, rp = get_webauthn_server(request)

        credentials = [{
            "type": "public-key",
            "id": ensure_bytes(cred.credential_id),
            "transports": ["usb", "nfc", "ble", "internal"],
        } for cred in user.webauthn_credentials.all()]

        auth_data, state = server.authenticate_begin(credentials)

        challenge = state.get("challenge")
        if isinstance(challenge, str):
            challenge_bytes = ensure_bytes(challenge)
            state["challenge"] = challenge_bytes
        else:
            challenge_bytes = challenge

        challenge_base64 = base64.b64encode(challenge_bytes).decode("utf-8")

        state_for_session = state.copy()
        state_for_session["challenge_base64"] = challenge_base64
        state_for_session.pop("challenge", None)

        request.session["state"] = state_for_session
        request.session["user_id"] = user.id

        response_data = {
            "status": "success",
            "publicKey": {
                "challenge": challenge_base64,
                "timeout": getattr(auth_data, "timeout", 60000),
                "rpId": rp.id,
                "allowCredentials": [{
                    "type": "public-key",
                    "id": base64.b64encode(ensure_bytes(cred.credential_id)).decode("utf-8"),
                    "transports": ["usb", "nfc", "ble", "internal"],
                } for cred in user.webauthn_credentials.all()],
                "userVerification": "preferred",
            },
        }
        return JsonResponse(response_data)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)

@csrf_exempt
def authenticate_complete(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Only POST allowed")

    try:
        data = json.loads(request.body)
        state = request.session.get("state")
        user_id = request.session.get("user_id")
        if not state or not user_id:
            return HttpResponseBadRequest("Session expired")

        if 'challenge_base64' in state:
            challenge_bytes = base64.b64decode(state['challenge_base64'])
            challenge_urlsafe = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8')
            state = {
                'challenge': challenge_urlsafe,
                'user_verification': state.get('user_verification', 'preferred'),
                'rpId': state.get('rpId', None)
            }
        else:
            return HttpResponseBadRequest("Invalid session state")

        user = User.objects.get(id=user_id)
        server, _ = get_webauthn_server(request)

        credential_id = ensure_bytes(data["credentialId"])
        client_data_json = ensure_bytes(data["clientDataJSON"])
        authenticator_data = ensure_bytes(data["authenticatorData"])
        signature = ensure_bytes(data["signature"])

        class CredWrapper:
            def __init__(self, credential_id, public_key, sign_count):
                self.credential_id = credential_id
                self.public_key = public_key
                self.sign_count = sign_count

        user_creds = []
        for cred in user.webauthn_credentials.all():
            raw_public_key = ensure_bytes(cred.public_key)
            cose_key_dict = cbor2.loads(raw_public_key)
            public_key_obj = CoseKey.parse(cose_key_dict)

            user_creds.append(CredWrapper(
                credential_id=ensure_bytes(cred.credential_id),
                public_key=public_key_obj,
                sign_count=cred.sign_count
            ))

        matching_cred = next((c for c in user_creds if c.credential_id == credential_id), None)
        if matching_cred is None:
            return HttpResponseBadRequest("Credential not registered")

        auth_response = AuthenticationResponse.from_dict({
            "rawId": credential_id,
            "response": {
                "clientDataJSON": client_data_json,
                "authenticatorData": authenticator_data,
                "signature": signature
            }
        })

        auth_data = server.authenticate_complete(
            state,
            [matching_cred],
            auth_response
        )

        new_sign_count = getattr(auth_data, "new_sign_count", None) or getattr(auth_data, "counter", None)
        if new_sign_count is not None:
            cred_obj = user.webauthn_credentials.get(credential_id=credential_id)
            cred_obj.sign_count = new_sign_count
            cred_obj.save()

        login(request, user)
        return JsonResponse({"status": "ok"})

    except Exception as e:
        import traceback
        print(f"Error in authenticate_complete: {str(e)}")
        print(traceback.format_exc())
        return HttpResponseBadRequest(f"Server error: {str(e)}")
