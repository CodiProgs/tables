import { createLoader } from '/static/js/ui-utils.js'

export default class SelectHandler {
	static setupSelects({ data = null, url = null, select = null }) {
		if (select) {
			if (data) {
				const dropdown = select.querySelector('.select__dropdown')

				if (dropdown) {
					dropdown.replaceChildren(...this.createSelectOptions(data))
					this.attachOptionHandlers(select)
				}
			}
			this.setupSelectBehavior(select, url)
		} else {
			const selects = document.querySelectorAll('.select')

			if (!selects.length) return

			selects.forEach(select => {
				if (data) {
					const dropdown = select.querySelector('.select__dropdown')
					if (dropdown) {
						dropdown.replaceChildren(...this.createSelectOptions(data))
						this.attachOptionHandlers(select)
					}
				}
				this.setupSelectBehavior(select, url)
			})
		}
	}

	static updateSelectOptions(select, data) {
		if (!select || !data) return

		const dropdown = select.querySelector('.select__dropdown')
		if (!dropdown) return

		dropdown.innerHTML = ''

		const options = this.createSelectOptions(data)
		dropdown.append(...options)

		this.attachOptionHandlers(select)

		const input = select.querySelector('.select__input')
		const text = select.querySelector('.select__text')
		if (input) input.value = ''
		if (text) text.textContent = ''
		select.classList.remove('has-value')

		return dropdown
	}

	static createSelectOptions(data) {
		return data.map(item => {
			const option = document.createElement('div')
			option.className = 'select__option'
			option.tabIndex = 0
			option.dataset.value = item.id
			option.textContent = item.name
			return option
		})
	}

	static async fetchSelectOptions(url) {
		const loader = createLoader()
		document.body.appendChild(loader)
		try {
			const response = await fetch(url, {
				headers: { 'X-Requested-With': 'XMLHttpRequest' },
			})
			if (!response.ok) {
				throw new Error(`Ошибка загрузки данных с ${url}: ${response.status}`)
			}
			return await response.json()
		} catch (error) {
			console.error('Ошибка получения данных для select:', error)
			return []
		} finally {
			loader.remove()
		}
	}

	static async populateSelectOptions(select, url) {
		const dropdown = select.querySelector('.select__dropdown')
		if (!dropdown) return

		const data = await this.fetchSelectOptions(url)

		dropdown.replaceChildren(...this.createSelectOptions(data))
		this.attachOptionHandlers(select)
	}

	static setupSelectBehavior(select, url) {
		const control = select.querySelector('.select__control')
		const dropdown = select.querySelector('.select__dropdown')
		const clearButton = select.querySelector('.select__clear')
		const input = select.querySelector('.select__input')
		const text = select.querySelector('.select__text')

		const updateClearButton = () => {
			if (input.value) {
				select.classList.add('has-value')
			} else {
				select.classList.remove('has-value')
			}
		}

		clearButton.addEventListener('click', e => {
			e.stopPropagation()
			input.value = ''
			const placeholder = input.getAttribute('placeholder') || ''
			text.textContent = placeholder
			text.classList.add('select__placeholder')
			select.classList.remove('has-value')
		})

		const toggleSelect = async () => {
			if (!dropdown.hasChildNodes() && url) {
				await this.populateSelectOptions(select, url)
			}

			select.classList.toggle('active')
		}

		control.addEventListener('click', toggleSelect)
		control.addEventListener('keydown', e => {
			if (e.key === 'Enter') toggleSelect()
		})

		document.addEventListener('click', e => {
			if (!select.contains(e.target)) {
				select.classList.remove('active')
			}
		})

		updateClearButton()
	}

	static attachOptionHandlers(select) {
		const input = select.querySelector('.select__input')
		const text = select.querySelector('.select__text')

		select.querySelectorAll('.select__option').forEach(option => {
			const handleSelect = () => {
				text.textContent = option.textContent
				input.value = option.dataset.value

				select.classList.remove('active')
				select.classList.add('has-value')

				text.classList.remove('select__placeholder')
			}

			option.addEventListener('click', handleSelect)
			option.addEventListener('keydown', e => {
				if (e.key === 'Enter') handleSelect()
			})
		})
	}
}
