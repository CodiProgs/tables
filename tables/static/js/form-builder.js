export class FormBuilder {
	static selectComponentCache = null

	constructor(table, columnWidths, ths) {
		this.table = table
		this.columnWidths = columnWidths
		this.ths = ths
	}

	async buildForm(id, rowId = null, targetRow = null) {
		const formContainer = this.createFormContainer(id)
		const [fragment, buttons] = await Promise.all([
			this.buildFormColumns(rowId),
			this.createButtonContainer(targetRow),
		])

		if (rowId) formContainer.classList.add('create-form--edit')

		formContainer.append(fragment, buttons)
		this.insertForm(formContainer)
		this.setFormPosition(formContainer, targetRow)

		return formContainer
	}

	createFormContainer(id) {
		const form = document.createElement('form')
		form.className = 'create-form'
		form.id = id
		return form
	}

	async buildFormColumns(rowId) {
		const visibleHeaders = this.ths.filter(
			th => !th.classList.contains('hidden')
		)

		const columns = await Promise.all(
			visibleHeaders.map((th, index) => this.createColumn(th, index, rowId))
		)

		return columns.reduce((fragment, column) => {
			fragment.appendChild(column)
			return fragment
		}, document.createDocumentFragment())
	}

	async createColumn(th, index, rowId) {
		const colDiv = this.createColumnDiv(index)
		if (th.textContent.trim() === 'ID') {
			if (rowId) colDiv.append(this.createIdSpan(rowId))
			return colDiv
		}

		colDiv.append(await this.createColumnInput(th, index))

		return colDiv
	}

	async createColumnInput(th, index) {
		try {
			return th.dataset.columnType === 'select' ||
				th.dataset.columnType === 'is_enum_field' ||
				th.dataset.columnType === 'is_type_sign'
				? await this.createSelectComponent(th, index)
				: this.createTextInput(th, index)
		} catch (error) {
			console.error('Error creating input:', error)
			return this.createTextInput(th, index)
		}
	}

	async createSelectComponent(th, index) {
		if (!FormBuilder.selectComponentCache) {
			const response = await fetch('/components/select/', {
				headers: { 'X-Requested-With': 'XMLHttpRequest' },
			})
			const html = await response.text()
			FormBuilder.selectComponentCache = html
		}

		const dropdown = new DOMParser().parseFromString(
			FormBuilder.selectComponentCache,
			'text/html'
		).body.firstElementChild

		const input = dropdown.querySelector('.select__input')
		input.name = th.dataset.name || `field_${index}`
		input.id = `id_${input.name}`
		return dropdown
	}

	createTextInput(th, index) {
		const container = document.createElement('div')
		container.className = 'input-container'

		const input = document.createElement('input')
		input.type = 'text'
		input.className = 'create-form__input'
		input.name = th.dataset.name || `field_${index}`

		const clearButton = document.createElement('i')
		clearButton.className = 'far fa-times clear-button'

		container.appendChild(input)
		container.appendChild(clearButton)
		return container
	}

	createButtonContainer(targetRow) {
		const buttons = document.createElement('div')
		buttons.className = `create-form__buttons ${this.calculateButtonPosition(
			targetRow
		)}`

		buttons.append(
			this.createButton('submit', 'Confirm'),
			this.createButton('button', 'Cancel', () => this.hideForm())
		)

		return buttons
	}

	calculateButtonPosition(targetRow) {
		if (!targetRow) return 'create-form__buttons--bottom'

		const allRows = Array.from(this.table.querySelectorAll('.table__row'))
		const rowIndex = allRows.indexOf(targetRow)

		return rowIndex > 2
			? 'create-form__buttons--top'
			: 'create-form__buttons--bottom'
	}

	createButton(type, text, onClick) {
		const button = document.createElement('button')
		button.type = type
		button.className = 'button'
		button.textContent = text
		if (onClick) button.addEventListener('click', onClick)
		return button
	}

	createIdSpan(rowId) {
		const span = document.createElement('span')
		span.textContent = rowId
		return span
	}

	createColumnDiv(index) {
		const div = document.createElement('div')
		div.className = 'create-form__column'
		div.style.width = `${this.columnWidths[index]}px`
		return div
	}

	setFormPosition(formContainer, targetRow) {
		if (targetRow) {
			const topPosition =
				targetRow.offsetTop -
				(formContainer.offsetHeight - targetRow.offsetHeight) / 2

			formContainer.style.top = `${topPosition}px`
		}
	}

	insertForm(formContainer) {
		this.table.parentNode.insertBefore(formContainer, this.table.nextSibling)
	}

	hideForm() {
		const form = this.table.nextElementSibling
		if (form?.matches('.create-form')) form.remove()
	}
}
