export class Modal {
	constructor() {
		this.modal = null
	}

	async init() {
		const response = await fetch('/components/modal/', {
			headers: { 'X-Requested-With': 'XMLHttpRequest' },
		})
		const html = await response.text()

		this.modal = document.createElement('div')
		this.modal.innerHTML = html
		this.modal = this.modal.firstElementChild

		const content = document.querySelector('.container')
		content.inert = true
	}

	addEventListeners() {
		const closeBtn = this.modal.querySelector('.modal__close')
		const cancelBtn = this.modal.querySelector('.button--cancel')

		closeBtn.addEventListener('click', () => this.close())

		if (cancelBtn) {
			cancelBtn.addEventListener('click', () => {
				this.close()
			})
		}
	}

	async open(content, title = '') {
		if (!this.modal) await this.init()

		this.modal.querySelector('.modal__title').textContent = title
		this.modal.querySelector('.modal__body').innerHTML = content

		this.addEventListeners()

		document.body.appendChild(this.modal)

		this._modalKeydownHandler = e => {
			if (e.key === 'Enter' && !e.shiftKey) {
				const active = document.activeElement
				if (active.tagName === 'SELECT' || active.closest('.select')) {
					return
				}
				if (
					active.tagName !== 'INPUT' &&
					active.tagName !== 'SELECT' &&
					active.tagName !== 'TEXTAREA'
				) {
					const form = this.modal.querySelector('form')
					if (form) {
						e.preventDefault()
						form.requestSubmit()
					}
				}
			}
		}
		document.addEventListener('keydown', this._modalKeydownHandler)

		this.setFocusOnFirstInput()

		return this.modal
	}

	setFocusOnFirstInput() {
		setTimeout(() => {
			const inputs = this.modal.querySelectorAll(
				'input, select, textarea, button[type="submit"]'
			)

			for (const input of inputs) {
				const style = window.getComputedStyle(input)
				const isVisible =
					style.display !== 'none' &&
					style.visibility !== 'hidden' &&
					!input.hidden

				const isEnabled =
					!input.disabled && !input.readOnly && input.type !== 'hidden'

				if (isVisible && isEnabled) {
					input.focus()

					if (
						input.tagName === 'INPUT' &&
						(input.type === 'text' ||
							input.type === 'email' ||
							input.type === 'number')
					) {
						const length = input.value.length
						if (length > 0) {
							input.setSelectionRange(length, length)
						}
					}

					break
				}
			}
		}, 50)
	}

	close() {
		const content = document.querySelector('.container')
		content.inert = false

		if (this._modalKeydownHandler) {
			document.removeEventListener('keydown', this._modalKeydownHandler)
			this._modalKeydownHandler = null
		}

		this.modal.remove()
	}
}
