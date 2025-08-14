import { showError, showSuccess } from '/static/js/ui-utils.js'

function setCookie(name, value, days = 365) {
	const expires = new Date(Date.now() + days * 864e5).toUTCString()
	document.cookie = name + '=' + value + '; expires=' + expires + '; path=/'
}

function getCookie(name) {
	return document.cookie
		.split('; ')
		.find(row => row.startsWith(name + '='))
		?.split('=')[1]
}

document.addEventListener('DOMContentLoaded', function () {
	const registerButton = document.querySelector('.login__register')
	if (registerButton) {
		registerButton.addEventListener('click', function () {
			const usernameInput = document.querySelector('#username')
			const passwordInput = document.querySelector('#password')

			const username = usernameInput.value
			const password = passwordInput.value

			register(username, password).catch(error => {
				console.error('Ошибка регистрации:', error)

				showError(error.message || 'Неизвестная ошибка')
			})
		})
	}

	const loginButton = document.querySelector('.login__btn')
	if (loginButton) {
		const credentialId = getCookie('credentialId')
		if (credentialId) {
			if (credentialId) {
				loginButton.innerHTML =
					'<span style="vertical-align:middle; margin-right:6px;">🟢</span>Войти по отпечатку без данных'
				loginButton.title =
					'Вы можете войти по отпечатку пальца без ввода данных пользователя'
				loginButton.classList.add('login__btn--fingerprint')
			} else {
				loginButton.innerHTML = 'Войти по отпечатку'
				loginButton.title = ''
			}
		}

		loginButton.addEventListener('click', function () {
			const usernameInput = document.querySelector('#username')

			const username = usernameInput.value

			login(username || undefined).catch(error => {
				console.error('Ошибка входа:', error)
				showError(error.message || 'Неизвестная ошибка')
			})
		})
	}
})

function base64UrlToUint8Array(base64Url) {
	const padding = '='.repeat((4 - (base64Url.length % 4)) % 4)
	const base64 = (base64Url + padding).replace(/-/g, '+').replace(/_/g, '/')
	const raw = atob(base64)
	const buffer = new Uint8Array(raw.length)
	for (let i = 0; i < raw.length; i++) {
		buffer[i] = raw.charCodeAt(i)
	}
	return buffer
}

function uint8ArrayToBase64(uint8Array) {
	return btoa(String.fromCharCode.apply(null, uint8Array))
}

async function register(username, password) {
	try {
		if (
			!window.PublicKeyCredential ||
			!navigator.credentials ||
			!navigator.credentials.create
		) {
			showError('Ваш браузер не поддерживает вход по отпечатку (WebAuthn)')
			return
		}

		const response = await fetch('/webauthn/register/begin/', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				Accept: 'application/json',
				'X-Requested-With': 'XMLHttpRequest',
			},
			body: JSON.stringify({
				username,
				password,
			}),
			credentials: 'same-origin',
		})

		if (!response.ok) {
			const errorText = await response.json()
			throw new Error(`${errorText.message}`)
		}

		const responseData = await response.json()
		const options = responseData.publicKey

		if (!options) {
			console.error('Ответ сервера не содержит publicKey:', responseData)
			throw new Error('Неверный формат ответа от сервера')
		}

		options.user.id = base64UrlToUint8Array(options.user.id)
		options.challenge = base64UrlToUint8Array(options.challenge)

		if (options.excludeCredentials) {
			options.excludeCredentials = options.excludeCredentials.map(cred => {
				cred.id = base64UrlToUint8Array(cred.id)
				return cred
			})
		}

		const credential = await navigator.credentials.create({
			publicKey: options,
		})

		const attestationResponse = {
			id: uint8ArrayToBase64(new Uint8Array(credential.rawId)),
			rawId: uint8ArrayToBase64(new Uint8Array(credential.rawId)),
			attestationObject: uint8ArrayToBase64(
				new Uint8Array(credential.response.attestationObject)
			),
			clientDataJSON: uint8ArrayToBase64(
				new Uint8Array(credential.response.clientDataJSON)
			),
			type: credential.type,
		}

		const completeResponse = await fetch('/webauthn/register/complete/', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				Accept: 'application/json',
			},
			body: JSON.stringify(attestationResponse),
			credentials: 'same-origin',
		})

		if (!completeResponse.ok) {
			const errorText = await completeResponse.text()
			throw new Error(`Ошибка завершения регистрации: ${errorText}`)
		}

		const result = await completeResponse.json()

		const credentialId = uint8ArrayToBase64(new Uint8Array(credential.rawId))
		setCookie('credentialId', credentialId)

		showSuccess(
			'Регистрация прошла успешно. Вы можете войти в систему с помощью отпечатка пальца.'
		)

		return result
	} catch (error) {
		throw error
	}
}

async function login(username) {
	try {
		let body = {}
		if (username) {
			body.username = username
		} else {
			const credentialId = getCookie('credentialId')
			if (credentialId) {
				body.credentialId = credentialId
			}
		}

		if (
			!window.PublicKeyCredential ||
			!navigator.credentials ||
			!navigator.credentials.get
		) {
			showError('Ваш браузер не поддерживает вход по отпечатку (WebAuthn)')
			return
		}

		const response = await fetch('/webauthn/authenticate/begin/', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				Accept: 'application/json',
				'X-Requested-With': 'XMLHttpRequest',
			},
			body: JSON.stringify(body),
			credentials: 'same-origin',
		})

		if (!response.ok) {
			const errorText = await response.json()
			throw new Error(`${errorText.message}`)
		}

		const responseData = await response.json()
		const options = responseData.publicKey

		if (!options) {
			console.error('Ответ сервера не содержит publicKey:', responseData)
			throw new Error('Неверный формат ответа от сервера')
		}

		options.challenge = base64UrlToUint8Array(options.challenge)

		if (options.allowCredentials) {
			options.allowCredentials = options.allowCredentials.map(cred => {
				cred.id = base64UrlToUint8Array(cred.id)
				return cred
			})
		}

		const credential = await navigator.credentials.get({
			publicKey: options,
		})

		const authResponse = {
			credentialId: uint8ArrayToBase64(new Uint8Array(credential.rawId)),
			clientDataJSON: uint8ArrayToBase64(
				new Uint8Array(credential.response.clientDataJSON)
			),
			authenticatorData: uint8ArrayToBase64(
				new Uint8Array(credential.response.authenticatorData)
			),
			signature: uint8ArrayToBase64(
				new Uint8Array(credential.response.signature)
			),
		}

		const completeResponse = await fetch('/webauthn/authenticate/complete/', {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				Accept: 'application/json',
			},
			body: JSON.stringify(authResponse),
			credentials: 'same-origin',
		})

		if (!completeResponse.ok) {
			const errorText = await completeResponse.text()
			throw new Error(`${errorText}`)
		}

		const result = await completeResponse.json()

		const credentialId = uint8ArrayToBase64(new Uint8Array(credential.rawId))
		setCookie('credentialId', credentialId)

		window.location.href = '/'
		return result
	} catch (error) {
		throw error
	}
}
