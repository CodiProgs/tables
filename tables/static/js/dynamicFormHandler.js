import { Modal } from '/static/js/modal.js'
import SelectHandler from '/static/js/selectHandler.js'
import { TableManager } from '/static/js/table.js'
import {
	createLoader,
	getCSRFToken,
	showError,
	showSuccess,
} from '/static/js/ui-utils.js'

export class DynamicFormHandler {
	constructor(config) {
		this.config = {
			submitUrl: '',
			formId: '',
			...config,
		}
		this.currentEditId = null
		this.modal = null
	}

	async init(editId = null) {
		const loader = createLoader()
		document.body.appendChild(loader)

		try {
			this.currentEditId = editId ?? null

			await this.initializeForm()

			const modalContent = await this.fetchModalContent()

			if (modalContent) await this.openModal(modalContent)

			if (Array.isArray(this.config.dataUrls)) {
				for (const { id, url } of this.config.dataUrls) {
					const select = document.getElementById(id)

					if (select) {
						const selectParent = select.closest('.select')

						if (Array.isArray(url)) {
							await SelectHandler.setupSelects({
								data: url,
								select: selectParent,
							})
						} else if (
							(this.currentEditId || this.currentEditId === 0) &&
							url
						) {
							const response = await fetch(url, {
								headers: { 'X-Requested-With': 'XMLHttpRequest' },
							})

							if (response.ok) {
								const data = await response.json()
								await SelectHandler.setupSelects({
									data: data,
									select: selectParent,
								})
							} else {
								throw new Error('Failed to load select data')
							}
						} else {
							await SelectHandler.setupSelects({ url, select: selectParent })
						}
					} else {
						console.warn(`Select with id "${id}" not found.`)
					}
				}
			}
			if (this.shouldLoadEditData()) await this.loadEditData()

			this.setupForm()
		} catch (error) {
			console.error('Initialization error:', error)
			showError('Form initialization failed. Please try again.')
		} finally {
			loader.remove()
		}
	}

	async initializeForm() {
		if (this.config.createFormFunction) {
			await this.config.createFormFunction(this.config.formId)
		}
	}

	async fetchModalContent() {
		if (!this.config.modalConfig?.url) return null

		const url = new URL(this.config.modalConfig.url, window.location.origin)

		if (this.config.modalConfig.context) {
			Object.keys(this.config.modalConfig.context).forEach(key => {
				url.searchParams.append(key, this.config.modalConfig.context[key])
			})
		}

		const response = await fetch(url, {
			method: 'GET',
			headers: { 'X-Requested-With': 'XMLHttpRequest' },
		})
		return response.text()
	}

	async loadEditData() {
		try {
			const response = await fetch(
				`${this.config.getUrl}${this.currentEditId}/`,
				{ headers: { 'X-Requested-With': 'XMLHttpRequest' } }
			)

			if (!response.ok) throw new Error('Failed to load edit data')

			const { data } = await response.json()

			this.fillFormFields(data)
		} catch (error) {
			console.error('Data loading error:', error)
			showError(error.message || 'Failed to load required data')
		}
	}

	fillFormFields(data) {
		const form = document.getElementById(this.config.formId)

		if (!form) return

		for (const [fieldName, value] of Object.entries(data)) {
			const element = form.querySelector(`[name="${fieldName}"], #${fieldName}`)

			if (!element) continue

			const processedValue = fieldName === 'amount' ? Math.abs(value) : value
			this.setFieldValue(element, processedValue)

			element.dispatchEvent(new Event('change', { bubbles: true }))
		}
	}

	setFieldValue(element, value) {
		if (element.type === 'checkbox') {
			element.checked = Boolean(value)
		} else if (element.classList.contains('select__input')) {
			this.setSelectValue(element, value)
		} else {
			if (element.id === 'report_date' && value) {
				const dateParts = value.split('-')
				if (dateParts.length === 3) {
					value = `${dateParts[0]}-${dateParts[1]}`
				}
			}

			element.value = value ?? ''

			if (element.type === 'hidden' || element.hasAttribute('hidden')) {
				element.setAttribute('value', value)
			}
		}
	}

	setSelectValue(selectInput, value) {
		const selectContainer = selectInput.closest('.select')
		const option = selectContainer?.querySelector(
			`.select__option[data-value="${value}"]`
		)
		if (option) {
			const textElement = selectContainer.querySelector('.select__text')
			if (textElement) {
				textElement.textContent = option.textContent
				textElement.classList.remove('select__placeholder')
			}
			selectInput.value = value
		} else {
			if (selectInput.type === 'hidden' || selectInput.hasAttribute('hidden')) {
				selectInput.setAttribute('value', value)
			}
		}
	}

	async openModal(content) {
		this.modal = new Modal()
		await this.modal.open(content, this.config.modalConfig.title || 'Форма')
	}

	setupForm() {
		const form = document.getElementById(this.config.formId)
		if (form) {
			form.addEventListener('submit', this.handleSubmit.bind(this))
		}
	}

	async handleSubmit(e) {
		e.preventDefault()
		const form = e.target

		const loader = createLoader()
		document.body.appendChild(loader)

		try {
			const formData = new FormData(form)
			const csrfToken = this.getCSRFToken(form)

			const url = this.currentEditId
				? `${this.config.submitUrl}${this.currentEditId}/`
				: this.config.submitUrl

			let requestOptions = {
				method: 'POST',
				headers: {
					'X-CSRFToken': csrfToken,
				},
			}

			requestOptions.body = formData

			const response = await fetch(url, requestOptions)

			await this.handleFormResponse(response)
		} catch (error) {
			this.handleFormError(error)
		} finally {
			loader.remove()
		}
	}

	getCSRFToken(form) {
		return (
			form.querySelector('[name=csrfmiddlewaretoken]')?.value || getCSRFToken()
		)
	}

	async handleFormResponse(response) {
		if (!response.ok) {
			const error = await response.json()
			throw new Error(error.message || 'Form submission failed')
		}

		const result = await response.json()

		this.config.onSuccess?.(result)

		this.closeForm()
		showSuccess()
	}

	handleFormError(error) {
		console.error('Form error:', error)
		showError(error.message)
	}

	closeForm() {
		if (this.modal) {
			this.modal.close()
		} else {
			TableManager.hideForm(this.config.formId, this.config.tableId)
		}
	}

	shouldLoadEditData() {
		return this.currentEditId && this.config.getUrl
	}
}
