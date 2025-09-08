import SelectHandler from './selectHandler.js'
import { FormBuilder } from '/static/js/form-builder.js'
import {
	createLoader,
	getCSRFToken,
	showError,
	showSuccess,
} from '/static/js/ui-utils.js'

const DOM_HELPER = {
	createElement: (tag, className = '') => {
		const element = document.createElement(tag)
		if (className) element.className = className
		return element
	},
	removeElement: element => element?.remove(),
	toggleElementClass: (element, className, shouldAdd) =>
		element.classList.toggle(className, shouldAdd),
	applyStyles: (element, styles) => Object.assign(element.style, styles),
}

const CookieUtils = {
	setCookie(name, value, days = 30) {
		const expires = new Date()
		expires.setTime(expires.getTime() + days * 24 * 60 * 60 * 1000)
		document.cookie = `${name}=${encodeURIComponent(
			JSON.stringify(value)
		)};expires=${expires.toUTCString()};path=/`
	},

	getCookie(name) {
		const nameEQ = `${name}=`
		const ca = document.cookie.split(';')
		for (let i = 0; i < ca.length; i++) {
			let c = ca[i]
			while (c.charAt(0) === ' ') c = c.substring(1, c.length)
			if (c.indexOf(nameEQ) === 0) {
				try {
					return JSON.parse(
						decodeURIComponent(c.substring(nameEQ.length, c.length))
					)
				} catch (e) {
					console.error('Error parsing cookie value:', e)
					return null
				}
			}
		}
		return null
	},
}

class ColumnSizeCalculator {
	static CONFIG = {
		select: { min: 150, max: 200 },
		number: { min: 60, max: 90 },
		default: { min: 50, max: 200 },
		sign: { min: 50, max: 80 },
		amount: { min: 60, max: 90 },
		checkbox: { min: 50, max: 100 },
		percent: { min: 50, max: 80 },
		boolean: { min: 50, max: 80 },
	}

	constructor(tableElement, headerCells, initialWidths) {
		this.tableElement = tableElement
		this.headerCells = headerCells
		this.initialWidths = initialWidths
	}

	calculateInitialWidths() {
		if (this.initialWidths && this.initialWidths.length > 0) {
			this.applyColumnWidths(this.initialWidths)
			this.tableElement.style.visibility = 'visible'
			return this.initialWidths
		}

		const visibleHeaders = this.headerCells.filter(
			header => !header.classList.contains('hidden')
		)

		let computedWidths = Array.from(
			this.tableElement.querySelector('colgroup').children
		).map((col, index) => this.calculateColumnWidth(col, index, visibleHeaders))

		const container = this.tableElement.parentElement
		const tableWidth = container.clientWidth - 1
		const visibleColumnsCount = visibleHeaders.length

		if (tableWidth <= 560 && visibleColumnsCount <= 4) {
			this.handleSmallContainer(computedWidths, tableWidth, visibleHeaders)
		}

		this.applyColumnWidths(computedWidths)
		requestAnimationFrame(() => {
			this.tableElement.style.visibility = 'visible'
		})

		return computedWidths
	}

	handleSmallContainer(computedWidths, containerWidth, visibleHeaders) {
		const fixedColumns = visibleHeaders.filter(header => {
			const type = header.getAttribute('data-column-type') || 'default'
			return (
				type === 'fixed' ||
				type === 'checkbox' ||
				type === 'icon' ||
				type === 'percent'
			)
		})

		const flexibleColumns = visibleHeaders.filter(
			header => !fixedColumns.includes(header)
		)

		const totalFlexWidth = flexibleColumns.reduce((sum, header) => {
			const index = this.headerCells.indexOf(header)
			return sum + computedWidths[index]
		}, 0)

		const totalFixedWidth = fixedColumns.reduce((sum, header) => {
			const index = this.headerCells.indexOf(header)
			return sum + computedWidths[index]
		}, 0)

		const remainingWidth = containerWidth - totalFixedWidth
		const scaleFactor = remainingWidth / totalFlexWidth

		flexibleColumns.forEach(header => {
			const index = this.headerCells.indexOf(header)
			const type = header.getAttribute('data-column-type') || 'default'

			const { min, max } =
				ColumnSizeCalculator.CONFIG[type] || ColumnSizeCalculator.CONFIG.default

			let newWidth = computedWidths[index] * scaleFactor
			newWidth = Math.max(min, Math.min(newWidth, max))
			computedWidths[index] = newWidth
		})

		const currentTotal = computedWidths.reduce((a, b) => a + b, 0)
		const widthDiff = containerWidth - currentTotal

		if (widthDiff !== 0) {
			const lastFlexIndex = this.headerCells.indexOf(
				flexibleColumns[flexibleColumns.length - 1]
			)
			computedWidths[lastFlexIndex] += widthDiff
		}
	}

	applyColumnWidths(widths) {
		widths.forEach((width, index) => {
			if (width > 0) {
				const cells = this.tableElement.querySelectorAll(
					`td:nth-child(${index + 1})`
				)
				cells.forEach(cell => {
					cell.style.maxWidth = `${width}px`
				})
				if (this.headerCells[index]) {
					this.headerCells[index].style.maxWidth = `${width}px`
				}
			}
		})
	}

	calculateColumnWidth(col, index, visibleHeaders) {
		const header = this.headerCells[index]
		if (!header || header.classList.contains('hidden')) return 0

		let type = header.getAttribute('data-column-type') || 'default'

		if (
			type === 'select' &&
			header.classList.contains('table__cell-header-sign')
		) {
			type = 'sign'
		}

		const { min, max } =
			ColumnSizeCalculator.CONFIG[type] || ColumnSizeCalculator.CONFIG.default

		let defaultWidth = col.offsetWidth * 2
		if (visibleHeaders.length === 1) {
			defaultWidth = this.calculateMobileWidth()
		}

		return Math.min(Math.max(defaultWidth, min), max)
	}

	calculateMobileWidth() {
		const container = this.tableElement.parentElement
		const scrollbarWidth = container.offsetWidth - container.clientWidth
		return container.offsetWidth - scrollbarWidth - 3
	}
}

class ResizeHandler {
	constructor(tableInstance) {
		this.table = tableInstance
		this.isResizing = false
		this.resizeLineElement = null
	}

	initializeResize(header) {
		const handle = header.querySelector('.table__resize-handle')
		if (!handle) return

		const handler = e => this.startResize(e, header)
		handle.addEventListener('mousedown', handler)
		handle.addEventListener('touchstart', e => {
			e.preventDefault()
			handler(e.touches[0])
		})
		this.table.resizeHandlers.set(handle, handler)
	}

	startResize(event, header) {
		this.isResizing = true
		this.resizedColumn =
			this.table.columnGroup.children[this.table.headerCells.indexOf(header)]
		this.initialX = event.touches ? event.touches[0].clientX : event.clientX
		this.initialWidth = this.resizedColumn.offsetWidth

		document.body.classList.add('resize-active')

		this.createResizeLine()
		this.setupResizeListeners()
	}

	createResizeLine() {
		this.resizeLineElement = DOM_HELPER.createElement(
			'div',
			'table__resize-line'
		)

		const tableRect = this.table.tableElement.getBoundingClientRect()
		const columnRect = this.resizedColumn.getBoundingClientRect()
		const initialLeft = columnRect.right - tableRect.left

		DOM_HELPER.applyStyles(this.resizeLineElement, {
			display: 'block',
			left: `${initialLeft}px`,
			height: `${tableRect.height}px`,
		})

		this.table.tableElement.parentElement.appendChild(this.resizeLineElement)
	}

	setupResizeListeners() {
		const moveHandler = e => {
			e.preventDefault()
			this.handleResizeMove(e)
		}
		const endHandler = () => this.finalizeResize()

		document.addEventListener('mousemove', moveHandler)
		document.addEventListener('mouseup', endHandler)

		document.addEventListener('touchmove', moveHandler, { passive: false })
		document.addEventListener('touchend', endHandler)

		this.moveHandler = moveHandler
		this.endHandler = endHandler
	}

	handleResizeMove(event) {
		if (!this.isResizing) return

		cancelAnimationFrame(this.animationFrame)
		this.animationFrame = requestAnimationFrame(() => {
			const clientX = event.touches ? event.touches[0].clientX : event.clientX
			this.updateResizeLine(clientX)
			this.calculateNewWidth(clientX)
		})
	}

	updateResizeLine(clientX) {
		const tableRect = this.table.tableElement.getBoundingClientRect()
		DOM_HELPER.applyStyles(this.resizeLineElement, {
			left: `${clientX - tableRect.left}px`,
			height: `${tableRect.height}px`,
		})
	}

	calculateNewWidth(clientX) {
		const deltaX = clientX - this.initialX
		this.newWidth = Math.max(
			this.initialWidth + deltaX,
			this.table.minColumnWidth
		)
	}

	finalizeResize() {
		if (!this.isResizing) return

		DOM_HELPER.removeElement(this.resizeLineElement)
		this.applyFinalWidth()
		this.cleanupResize()
	}

	applyFinalWidth() {
		const columnIndex = Array.from(this.table.columnGroup.children).indexOf(
			this.resizedColumn
		)

		DOM_HELPER.applyStyles(this.resizedColumn, {
			width: `${this.newWidth}px`,
			minWidth: `${this.newWidth}px`,
			maxWidth: `${this.newWidth}px`,
		})

		const headerCell = this.table.headerCells[columnIndex]
		if (headerCell) {
			DOM_HELPER.applyStyles(headerCell, {
				maxWidth: `${this.newWidth}px`,
			})
		}

		const cells = this.table.tableElement.querySelectorAll(
			`td:nth-child(${columnIndex + 1})`
		)
		cells.forEach(cell => {
			DOM_HELPER.applyStyles(cell, {
				maxWidth: `${this.newWidth}px`,
			})
		})

		this.table.columnWidths[columnIndex] = this.newWidth
		this.table.updateTableWidth()

		this.table.saveColumnWidths()
	}

	cleanupResize() {
		this.isResizing = false
		this.resizedColumn = null

		document.body.classList.remove('resize-active')

		document.removeEventListener('mousemove', this.moveHandler)
		document.removeEventListener('touchmove', this.moveHandler)
		document.removeEventListener('mouseup', this.endHandler)
		document.removeEventListener('touchend', this.endHandler)

		this.moveHandler = null
		this.endHandler = null
	}
}

class DropdownManager {
	constructor(tableInstance) {
		this.table = tableInstance
		this.currentDropdown = null
		this.currentToggleButton = null
		this.documentClickHandler = this.handleDocumentClick.bind(this)
	}

	async showDropdown(toggleButton) {
		try {
			if (this.currentDropdown && this.currentToggleButton !== toggleButton) {
				this.removeDropdown()
			}

			if (this.currentToggleButton === toggleButton) {
				this.removeDropdown()
				return
			}

			const dropdown = document.createElement('div')
			dropdown.className = 'table__dropdown'

			const hideItem = document.createElement('div')
			hideItem.className = 'table__dropdown-item'
			hideItem.textContent = 'Скрыть'
			hideItem.dataset.action = 'hide'

			const sortItem = document.createElement('div')
			sortItem.className = 'table__dropdown-item'
			sortItem.textContent = 'Сортировать'
			sortItem.dataset.action = 'sort'

			dropdown.appendChild(hideItem)
			dropdown.appendChild(sortItem)

			this.positionDropdown(toggleButton, dropdown)
			document.body.appendChild(dropdown)

			hideItem.addEventListener('mouseenter', async () => {
				const submenuContent = await this.fetchDropdownContent()
				this.showSubmenu(hideItem, submenuContent)
			})

			hideItem.addEventListener('mouseleave', e => {
				if (
					this.currentSubmenu &&
					!this.currentSubmenu.contains(e.relatedTarget)
				) {
					DOM_HELPER.removeElement(this.currentSubmenu)
					this.currentSubmenu = null
				}
			})

			sortItem.addEventListener('mouseenter', async () => {
				if (this.sortSubmenu) {
					DOM_HELPER.removeElement(this.sortSubmenu)
				}

				const sortSubmenu = document.createElement('div')
				sortSubmenu.className = 'table__submenu'

				const ascSort = document.createElement('div')
				ascSort.className = 'table__dropdown-item'
				ascSort.textContent = 'По возрастанию'
				ascSort.dataset.sortDir = 'asc'

				const descSort = document.createElement('div')
				descSort.className = 'table__dropdown-item'
				descSort.textContent = 'По убыванию'
				descSort.dataset.sortDir = 'desc'

				sortSubmenu.appendChild(ascSort)
				sortSubmenu.appendChild(descSort)

				const rect = sortItem.getBoundingClientRect()
				DOM_HELPER.applyStyles(sortSubmenu, {
					left: `${rect.right}px`,
					top: `${rect.top}px`,
				})

				document.body.appendChild(sortSubmenu)
				this.sortSubmenu = sortSubmenu

				const columnIndex = this.table.headerCells.indexOf(
					this.currentToggleButton.closest('th')
				)

				ascSort.addEventListener('click', () => {
					this.table.sortColumn(columnIndex, 'asc')
					this.removeDropdown()
				})

				descSort.addEventListener('click', () => {
					this.table.sortColumn(columnIndex, 'desc')
					this.removeDropdown()
				})
			})

			sortItem.addEventListener('mouseleave', e => {
				if (this.sortSubmenu && !this.sortSubmenu.contains(e.relatedTarget)) {
					DOM_HELPER.removeElement(this.sortSubmenu)
					this.sortSubmenu = null
				}
			})

			this.currentDropdown = dropdown
			this.currentToggleButton = toggleButton
			DOM_HELPER.toggleElementClass(toggleButton, 'active', true)

			document.addEventListener('click', this.documentClickHandler)
		} catch (error) {
			console.error('Dropdown error:', error)
		}
	}

	async showSubmenu(parentItem, submenuContent) {
		if (this.currentSubmenu) {
			DOM_HELPER.removeElement(this.currentSubmenu)
		}

		const submenu = submenuContent.cloneNode(true)
		submenu.className = 'table__submenu'

		const rect = parentItem.getBoundingClientRect()
		DOM_HELPER.applyStyles(submenu, {
			left: `${rect.right}px`,
			top: `${rect.top}px`,
		})

		document.body.appendChild(submenu)
		this.currentSubmenu = submenu

		submenu.addEventListener('mouseleave', e => {
			if (
				!e.relatedTarget ||
				!e.relatedTarget.closest('.table__dropdown-item[data-action="hide"]')
			) {
				DOM_HELPER.removeElement(this.currentSubmenu)
				this.currentSubmenu = null
			}
		})

		this.populateDropdownItems(submenu)
	}

	handleDocumentClick(event) {
		const isOutsideDropdown =
			this.currentDropdown && !this.currentDropdown.contains(event.target)
		const isOutsideSubmenu =
			this.currentSubmenu && !this.currentSubmenu.contains(event.target)
		const isOutsideButton =
			this.currentToggleButton &&
			!this.currentToggleButton.contains(event.target)

		if (
			(isOutsideDropdown && isOutsideSubmenu && isOutsideButton) ||
			(isOutsideDropdown && !this.currentSubmenu)
		) {
			this.removeDropdown()
		}
	}

	async fetchDropdownContent() {
		if (!this.constructor.dropdownContentCache) {
			const response = await fetch('/components/table-dropdown/', {
				headers: { 'X-Requested-With': 'XMLHttpRequest' },
			})
			this.constructor.dropdownContentCache = await response.text()
		}
		return new DOMParser().parseFromString(
			this.constructor.dropdownContentCache,
			'text/html'
		).body.firstElementChild
	}

	positionDropdown(toggleButton, dropdown) {
		const rect = toggleButton.getBoundingClientRect()
		DOM_HELPER.applyStyles(dropdown, {
			left: `${rect.left}px`,
			top: `${rect.bottom}px`,
		})
	}

	populateDropdownItems(dropdownElement) {
		const template = dropdownElement.querySelector('.table__column-item')
		this.table.headerCells.forEach((header, index) => {
			const item = this.createDropdownItem(header, index, template)
			dropdownElement.appendChild(item)
		})
		DOM_HELPER.removeElement(template)
	}

	createDropdownItem(header, index, template) {
		const item = template.cloneNode(true)
		const checkbox = item.querySelector('input')
		const label = item.querySelector('label')

		const checkboxId = this.configureCheckbox(checkbox, header, index)

		label.setAttribute('for', checkboxId)
		this.configureLabel(label, header.textContent)
		this.addItemInteraction(item, index)

		return item
	}

	configureCheckbox(checkbox, header, index) {
		const checkboxId = `column-${index}`

		checkbox.id = checkboxId
		checkbox.checked = !header.classList.contains('hidden')
		checkbox.disabled = this.table.headerCells.length === 1

		return checkboxId
	}

	configureLabel(label, text) {
		const textSpan = DOM_HELPER.createElement('span', 'checkbox__text')
		textSpan.textContent = text.trim()
		label.appendChild(textSpan)
	}

	addItemInteraction(item, index) {
		const label = item.querySelector('label')

		label.addEventListener('click', e => {
			e.stopPropagation()

			this.table.toggleColumnVisibility(index)
		})
	}

	removeDropdown() {
		document.removeEventListener('click', this.documentClickHandler)

		DOM_HELPER.removeElement(this.currentDropdown)
		DOM_HELPER.removeElement(this.currentSubmenu)
		DOM_HELPER.removeElement(this.sortSubmenu)

		if (this.currentToggleButton) {
			DOM_HELPER.toggleElementClass(this.currentToggleButton, 'active', false)
		}

		this.currentDropdown = null
		this.currentToggleButton = null
		this.currentSubmenu = null
		this.sortSubmenu = null
	}
}

class ColumnVisibilityController {
	constructor(tableInstance) {
		this.table = tableInstance
	}

	toggleVisibility(index) {
		const columnChildren = Array.from(this.table.columnGroup.children)

		const elements = [
			columnChildren[index],
			this.table.headerCells[index],
			...this.table.tableElement.querySelectorAll(`td:nth-child(${index + 1})`),
		]

		elements.forEach(element =>
			DOM_HELPER.toggleElementClass(
				element,
				'hidden',
				!element.classList.contains('hidden')
			)
		)

		this.updateColumnState(index)
		this.table.syncFormColumnVisibility(index)
		this.table.updateLastColumnHighlight()
	}

	updateColumnState(index) {
		const isHidden =
			this.table.columnGroup.children[index].classList.contains('hidden')

		if (isHidden && this.table.columnWidths[index] > 0) {
			this.table.columnGroup.children[index].dataset.savedWidth =
				this.table.columnWidths[index]
			this.table.columnWidths[index] = 0
		} else if (!isHidden && this.table.columnWidths[index] === 0) {
			const savedWidth = parseInt(
				this.table.columnGroup.children[index].dataset.savedWidth || '0'
			)
			this.table.columnWidths[index] =
				savedWidth > 0 ? savedWidth : this.table.minColumnWidth
		} else if (!isHidden) {
			this.table.columnWidths[index] =
				this.table.columnGroup.children[index].offsetWidth
		}

		this.table.updateTableWidth()
		this.table.saveColumnWidths()
	}
}

class ResizableTable {
	constructor(tableElement, initialColumnWidths = []) {
		this.tableElement = tableElement
		this.minColumnWidth = 50

		const savedWidths = this.loadColumnWidths()

		this.columnWidths =
			savedWidths ||
			(Array.isArray(initialColumnWidths) ? initialColumnWidths : [])

		this.resizeHandlers = new Map()

		this.resizeHandler = new ResizeHandler(this)
		this.dropdownManager = new DropdownManager(this)
		this.visibilityController = new ColumnVisibilityController(this)

		this.initializeTable()
	}

	applyColumnVisibility(hiddenState) {
		if (
			!hiddenState ||
			!Array.isArray(hiddenState) ||
			hiddenState.length !== this.headerCells.length
		) {
			return
		}

		hiddenState.forEach((isHidden, index) => {
			if (isHidden) {
				const elements = [
					this.columnGroup.children[index],
					this.headerCells[index],
					...this.tableElement.querySelectorAll(`td:nth-child(${index + 1})`),
				]

				elements.forEach(element => {
					if (element) element.classList.add('hidden')
				})
			}
		})

		this.updateLastColumnHighlight()
		this.updateTableWidth()
	}

	saveColumnWidths() {
		const tableId = this.tableElement.id
		if (!tableId) return

		if (this.columnWidths && this.columnWidths.length > 0) {
			const columnData = {
				widths: this.columnWidths,
				hidden: Array.from(this.columnGroup.children).map(col =>
					col.classList.contains('hidden')
				),
			}

			CookieUtils.setCookie(`table_widths_${tableId}`, columnData, 365)
		}
	}

	loadColumnWidths() {
		const tableId = this.tableElement.id
		if (!tableId) return null

		try {
			const columnData = CookieUtils.getCookie(`table_widths_${tableId}`)

			if (!columnData) return null

			if (Array.isArray(columnData)) {
				return columnData
			}

			this.hiddenState = columnData.hidden

			return columnData.widths || null
		} catch (e) {
			console.error('Ошибка при загрузке ширин столбцов:', e)
			return null
		}
	}

	initializeTable() {
		this.validateTableElement()
		this.cacheTableElements()
		this.setupInitialLayout()
		this.addEventListeners()
	}

	validateTableElement() {
		if (!this.tableElement || !this.tableElement.querySelector('colgroup')) {
			throw new Error('Invalid table structure')
		}
	}

	cacheTableElements() {
		this.headerCells = Array.from(this.tableElement.querySelectorAll('th'))
		this.columnGroup = this.tableElement.querySelector('colgroup')

		if (!this.columnGroup) {
			throw new Error('colgroup element is missing in the table')
		}
	}

	setupInitialLayout() {
		if (
			this.columnWidths &&
			this.columnWidths.length > 0 &&
			this.columnWidths.length !== this.headerCells.length
		) {
			console.warn(
				`Количество сохраненных ширин (${this.columnWidths.length}) не соответствует количеству столбцов (${this.headerCells.length}). Будут вычислены новые значения.`
			)
			this.columnWidths = []
		}

		const calculator = new ColumnSizeCalculator(
			this.tableElement,
			this.headerCells,
			this.columnWidths
		)

		if (!this.columnWidths || this.columnWidths.length === 0) {
			this.columnWidths = calculator.calculateInitialWidths()
			this.saveColumnWidths()
		} else {
			calculator.applyColumnWidths(this.columnWidths)
			this.tableElement.style.visibility = 'visible'
		}

		this.applyColumnSizes()

		if (this.hiddenState) {
			this.applyColumnVisibility(this.hiddenState)
		}
	}

	applyColumnSizes() {
		Array.from(this.columnGroup.children).forEach((col, index) => {
			const width = this.columnWidths[index]
			DOM_HELPER.applyStyles(col, {
				width: `${width}px`,
				minWidth: `${width}px`,
				maxWidth: `${width}px`,
			})
		})
		this.updateTableWidth()
	}

	addEventListeners() {
		this.headerCells.forEach(header =>
			this.resizeHandler.initializeResize(header)
		)
		this.addToggleButtons()
	}

	addToggleButtons() {
		this.headerCells.forEach(header => {
			const button = DOM_HELPER.createElement('div', 'table__column-toggle')
			header.appendChild(button)
			button.addEventListener('click', e => {
				this.handleToggleButtonClick(e, button)
			})
		})
	}

	handleToggleButtonClick(event, button) {
		event.stopPropagation()
		this.dropdownManager.showDropdown(button)
	}

	toggleColumnVisibility(index) {
		this.visibilityController.toggleVisibility(index)
	}

	updateTableWidth() {
		const totalWidth = this.columnWidths.reduce((sum, width, index) => {
			const isHidden =
				this.columnGroup.children[index].classList.contains('hidden')
			return sum + (isHidden ? 0 : width)
		}, 0)

		DOM_HELPER.applyStyles(this.tableElement, { width: `${totalWidth}px` })
	}

	syncFormColumnVisibility(index) {
		const formElement = this.tableElement.nextElementSibling
		if (formElement?.classList.contains('create-form')) {
			const display = this.columnGroup.children[index].classList.contains(
				'hidden'
			)
				? 'none'
				: 'block'
			DOM_HELPER.applyStyles(formElement.children[index], { display })
		}
	}

	updateLastColumnHighlight() {
		const visibleHeaders = this.headerCells.filter(
			h => !h.classList.contains('hidden')
		)

		this.headerCells.forEach(header =>
			DOM_HELPER.toggleElementClass(header, 'table__cell-last', false)
		)

		this.tableElement
			.querySelectorAll('td')
			.forEach(cell =>
				DOM_HELPER.toggleElementClass(cell, 'table__cell-last', false)
			)

		if (visibleHeaders.length > 0) {
			const lastHeader = visibleHeaders[visibleHeaders.length - 1]
			const lastIndex = this.headerCells.indexOf(lastHeader)

			DOM_HELPER.toggleElementClass(lastHeader, 'table__cell-last', true)

			this.tableElement
				.querySelectorAll(`td:nth-child(${lastIndex + 1})`)
				.forEach(cell =>
					DOM_HELPER.toggleElementClass(cell, 'table__cell-last', true)
				)
		}
	}

	async createForm(formId, rowId = null, targetRow = null) {
		const formBuilder = new FormBuilder(
			this.tableElement,
			this.columnWidths,
			this.headerCells
		)
		await formBuilder.buildForm(formId, rowId, targetRow)
	}

	destroy() {
		this.resizeHandlers.forEach((handler, element) => {
			element.removeEventListener('mousedown', handler)
			element.removeEventListener('touchstart', handler)
		})
		this.dropdownManager.removeDropdown()
		this.headerCells = null
		this.columnGroup = null
		this.tableElement = null
	}

	sortColumn(columnIndex, direction) {
		if (columnIndex < 0 || columnIndex >= this.headerCells.length) {
			console.error('Invalid column index for sorting:', columnIndex)
			return
		}

		const headerCell = this.headerCells[columnIndex]
		const columnType = headerCell.dataset.columnType || 'default'
		const columnName = headerCell.dataset.name || ''

		this.updateSortingIndicator(columnIndex, direction)

		TableManager.sortTable(
			this.tableElement.id,
			columnIndex,
			direction,
			columnType
		)
	}

	updateSortingIndicator(columnIndex, direction) {
		this.headerCells.forEach(header => {
			header.classList.remove('table__cell-header--sorted-asc')
			header.classList.remove('table__cell-header--sorted-desc')
		})

		const header = this.headerCells[columnIndex]
		if (direction === 'asc') {
			header.classList.add('table__cell-header--sorted-asc')
		} else {
			header.classList.add('table__cell-header--sorted-desc')
		}
	}
}

export const TableManager = {
	tables: new Map(),
	tableFilters: new Map(),

	init() {
		this.destroyTables()
		document.querySelectorAll('.table').forEach(tableEl => {
			if (tableEl.id) {
				this.tables.set(tableEl.id, new ResizableTable(tableEl))
				this.formatCurrencyValues(tableEl.id)
			}
		})
		this.setInitialCellSelection()
		this.attachGlobalCellClickHandler()
	},

	initTable(tableId) {
		const tableEl = document.getElementById(tableId)
		if (tableEl) {
			this.tables.set(tableId, new ResizableTable(tableEl))
			this.formatCurrencyValues(tableId)
			this.setInitialSelectionForTable(tableId)
		}
	},

	sortTable(tableId, columnIndex, direction, columnType = 'default') {
		const table = document.getElementById(tableId)
		if (!table) {
			console.error(`Table with id "${tableId}" not found.`)
			return
		}

		const tbody = table.querySelector('tbody')
		if (!tbody) return

		const rows = Array.from(
			tbody.querySelectorAll('tr:not(.table__row--summary)')
		)
		const summaryRow = tbody.querySelector('.table__row--summary')

		const compareFunction = (a, b) => {
			const cellA = a.cells[columnIndex]
			const cellB = b.cells[columnIndex]

			if (!cellA || !cellB) return 0

			let valueA, valueB

			switch (columnType) {
				case 'amount':
					valueA = this.extractNumericValue(cellA.textContent)
					valueB = this.extractNumericValue(cellB.textContent)
					break
				case 'percent':
					valueA = parseFloat(cellA.textContent.replace('%', ''))
					valueB = parseFloat(cellB.textContent.replace('%', ''))
					break
				case 'date':
					valueA = new Date(cellA.textContent)
					valueB = new Date(cellB.textContent)
					break
				default:
					valueA = cellA.textContent.toLowerCase()
					valueB = cellB.textContent.toLowerCase()
			}

			if (valueA < valueB) return direction === 'asc' ? -1 : 1
			if (valueA > valueB) return direction === 'asc' ? 1 : -1
			return 0
		}

		rows.sort(compareFunction)

		rows.forEach(row => tbody.appendChild(row))

		if (summaryRow) {
			tbody.appendChild(summaryRow)
		}
	},

	extractNumericValue(text) {
		const numStr = text.replace(/[^\d.,]/g, '').replace(',', '.')
		return parseFloat(numStr) || 0
	},

	attachGlobalCellClickHandler() {
		document.addEventListener('click', event => this.onTableCellClick(event))
		document.addEventListener('contextmenu', event => {
			event.preventDefault()
			this.onTableCellClick(event, true)
		})
	},

	onTableCellClick(event) {
		const cell = event.target.closest('.table__cell')
		if (!cell) return

		document.querySelectorAll('.table__cell--selected').forEach(el => {
			el.classList.remove('table__cell--selected')
		})

		const table = cell.closest('.table')
		if (table) {
			table.querySelectorAll('.table__row--selected').forEach(row => {
				row.classList.remove('table__row--selected')
			})
		}

		cell.classList.add('table__cell--selected')

		cell.parentElement.classList.add('table__row--selected')
	},

	setInitialCellSelection() {
		document.querySelectorAll('.table__cell--selected').forEach(cell => {
			cell.classList.remove('table__cell--selected')
		})

		const firstTable = document.querySelector('.table')
		if (firstTable) {
			if (!firstTable.querySelector('.table__row--selected')) {
				const firstRow = Array.from(
					firstTable.querySelectorAll('.table__row')
				).find(row => !row.classList.contains('hidden-row'))
				if (firstRow) firstRow.classList.add('table__row--selected')
			}

			const firstRow = Array.from(
				firstTable.querySelectorAll('.table__row')
			).find(row => !row.classList.contains('hidden-row'))
			const firstCell = firstRow?.querySelector('.table__cell')
			if (firstCell) firstCell.classList.add('table__cell--selected')
		}
	},

	setInitialSelectionForTable(tableId) {
		const table = document.getElementById(tableId)
		if (!table) return
		const firstRow = table.querySelector('.table__row')
		if (firstRow) firstRow.classList.add('table__row--selected')
	},

	destroyTables() {
		this.tables.forEach(table => table.destroy())
		this.tables.clear()
	},

	formatCurrencyValues(tableId) {
		const table = document.getElementById(tableId)
		if (!table) return

		const headers = Array.from(table.querySelectorAll('thead th'))
		const amountColumnIndexes = headers
			.map((header, index) =>
				header.dataset.columnType === 'amount' ? index : -1
			)
			.filter(index => index !== -1)

		if (amountColumnIndexes.length !== 0) {
			amountColumnIndexes.forEach(colIndex => {
				const cells = table.querySelectorAll(
					`tbody td:nth-child(${colIndex + 1})`
				)
				cells.forEach(cell => {
					if (cell.classList.contains('table__cell--summary')) return
					if (cell.parentElement.classList.contains('table__row--summary'))
						return

					cell.style.textAlign = 'right'

					const text = cell.textContent.trim()

					if (text && /^[\d\s,.-]+(\s?р\.)?$/.test(text)) {
						const numText = text.replace(/\s?р\.$/, '').trim()
						const number = parseFloat(
							numText.replace(/\s/g, '').replace(',', '.')
						)
						if (!isNaN(number)) {
							const hadSuffix = /\s?р\.$/.test(text)
							cell.textContent =
								number === 0
									? hadSuffix
										? '0 р.'
										: '0'
									: this.formatNumber(number) + ' р.'
						}
					} else {
						if (text !== null && text !== '') {
							try {
								const textData = cell.textContent
									.trim()
									.replace(/'/g, '"')
									.replace(/Decimal\("([-]?[\d.]+)"\)/g, '$1')

								const data = JSON.parse(textData)
								const amountFormat = this.formatNumber(data.amount)

								cell.textContent = amountFormat + data.currency
								cell.classList.add(data.amount < 0 ? 'back-red' : 'back-green')
							} catch (err) {
								console.error(err)
							}
						} else {
							cell.textContent = 0
						}
					}
				})
			})
		}

		const percentColumnIndexes = headers
			.map((header, index) =>
				header.dataset.columnType === 'percent' ? index : -1
			)
			.filter(index => index !== -1)

		if (percentColumnIndexes.length !== 0) {
			percentColumnIndexes.forEach(colIndex => {
				const cells = table.querySelectorAll(
					`tbody td:nth-child(${colIndex + 1})`
				)
				const header = table.querySelector(
					`thead th:nth-child(${colIndex + 1})`
				)
				cells.forEach(cell => {
					if (cell.classList.contains('table__cell--summary')) return

					cell.style.textAlign = 'center'
					let text = cell.textContent.trim()

					text = text.replace(/%/g, '').trim()

					if (text) {
						cell.textContent = text + '%'
					}

					if (header.dataset.name === 'bonus_percentage') {
						if (cell.textContent !== '0%') {
							cell.classList.add('table__cell--changed')
						}
					}
				})
			})
		}
	},

	formatCurrencyValuesForRow(tableId, row) {
		const table = document.getElementById(tableId)

		if (!table || !row) return

		const headers = Array.from(table.querySelectorAll('thead th'))

		const amountColumnIndexes = headers
			.map((header, index) =>
				header.dataset.columnType === 'amount' ? index : -1
			)
			.filter(index => index !== -1)

		if (amountColumnIndexes.length !== 0) {
			amountColumnIndexes.forEach(colIndex => {
				const cell = row.querySelector(`td:nth-child(${colIndex + 1})`)
				if (cell && !cell.classList.contains('table__cell--summary')) {
					cell.style.textAlign = 'right'
					const text = cell.textContent.trim()

					if (text && /^[\d\s,.-]+(\s?р\.)?$/.test(text)) {
						const numText = text.replace(/\s?р\.$/, '').trim()
						const number = parseFloat(
							numText.replace(/\s/g, '').replace(',', '.')
						)
						if (!isNaN(number)) {
							const hadSuffix = /\s?р\.$/.test(text)
							cell.textContent =
								number === 0
									? hadSuffix
										? '0 р.'
										: '0'
									: this.formatNumber(number) + ' р.'
						}
					} else if (text !== null && text !== '') {
						try {
							const textData = cell.textContent
								.trim()
								.replace(/'/g, '"')
								.replace(/Decimal\("([-]?[\d.]+)"\)/g, '$1')

							const data = JSON.parse(textData)
							const amountFormat = this.formatNumber(data.amount)

							cell.textContent = amountFormat + data.currency

							cell.classList.add(data.amount < 0 ? 'back-red' : 'back-green')
						} catch (err) {
							console.error('Ошибка форматирования ячейки:', err)
						}
					} else {
						cell.textContent = '0'
					}
				}
			})
		}

		const percentColumnIndexes = headers
			.map((header, index) =>
				header.dataset.columnType === 'percent' ? index : -1
			)
			.filter(index => index !== -1)

		if (percentColumnIndexes.length !== 0) {
			percentColumnIndexes.forEach(colIndex => {
				const cell = row.querySelector(`td:nth-child(${colIndex + 1})`)
				const header = table.querySelector(
					`thead th:nth-child(${colIndex + 1})`
				)

				if (cell && !cell.classList.contains('table__cell--summary')) {
					cell.style.textAlign = 'center'

					let text = cell.textContent.trim()
					text = text.replace(/%/g, '').trim()

					if (text) {
						cell.textContent = text + '%'
					}

					if (header.dataset.name === 'bonus_percentage') {
						if (cell.textContent !== '0%') {
							cell.classList.add('table__cell--changed')
						}
					}
				}
			})
		}
	},

	async refresh(url, tableId) {
		const table = document.getElementById(tableId)
		if (!table) {
			console.error(`Table with id "${tableId}" not found.`)
			return
		}

		const loader = createLoader()
		document.body.appendChild(loader)

		try {
			const html = await this.fetchTableHTML(url)
			this.replaceTableContent(html, tableId)
			this.reinitializeTable(tableId)
			this.setInitialCellSelection()
			this.attachGlobalCellClickHandler()
		} catch (error) {
			showError(error.message)
		} finally {
			loader.remove()
		}
	},

	reinitializeTable(tableId) {
		const table = document.getElementById(tableId)
		if (!table) return

		let columnWidths = []
		if (this.tables.has(tableId)) {
			const oldTable = this.tables.get(tableId)
			columnWidths = [...oldTable.columnWidths]
			oldTable.destroy()
		}

		const newTable = new ResizableTable(table, columnWidths)
		this.tables.set(tableId, newTable)
		this.formatCurrencyValues(tableId)
	},

	updateTable(htmlContent, tableId) {
		this.replaceTableContent(htmlContent, tableId)

		this.reinitializeTable(tableId)
		this.setInitialCellSelection()
		this.attachGlobalCellClickHandler()
	},

	applyColumnWidthsForRow(tableId, row) {
		const table = document.getElementById(tableId)
		if (!table) {
			console.error(`Table with id "${tableId}" not found.`)
			return
		}

		const columnGroup = table.querySelector('colgroup')
		if (!columnGroup) {
			console.error('Required colgroup element is missing!')
			return
		}

		Array.from(columnGroup.children).forEach((col, index) => {
			const width = col.style.width || `${col.offsetWidth}px`
			const cell = row.querySelector(`td:nth-child(${index + 1})`)
			if (cell) {
				cell.style.maxWidth = width
			}
		})
	},

	async fetchTableHTML(url) {
		const response = await fetch(url, {
			headers: { 'X-Requested-With': 'XMLHttpRequest' },
		})
		if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)
		return await response.text()
	},

	async addTableRow(data, tableId) {
		const table = document.getElementById(tableId)
		if (!table) return

		let tableBody = table.querySelector('tbody.table__body')
		if (!tableBody) {
			tableBody = document.createElement('tbody')
			tableBody.className = 'table__body'
			table.appendChild(tableBody)
		}

		if (data.html) {
			document.querySelectorAll('.table__row--selected').forEach(row => {
				row.classList.remove('table__row--selected')
			})
			document.querySelectorAll('.table__cell--selected').forEach(cell => {
				cell.classList.remove('table__cell--selected')
			})

			const summaryRow = tableBody.querySelector('.table__row--summary')
			let newRow

			if (summaryRow) {
				summaryRow.insertAdjacentHTML('beforebegin', data.html)
				newRow = summaryRow.previousElementSibling
			} else {
				tableBody.insertAdjacentHTML('beforeend', data.html)
				newRow = tableBody.lastElementChild
			}

			document.querySelectorAll('.table__cell--selected').forEach(cell => {
				cell.classList.remove('table__cell--selected')
			})

			newRow.classList.add('table__row--selected')
			newRow
				.querySelector('.table__cell')
				?.classList.add('table__cell--selected')

			this.formatCurrencyValuesForRow(tableId, newRow)
			this.applyColumnWidthsForRow(tableId, newRow)
			this.attachRowCellHandlers(newRow)

			return newRow
		}
	},

	updateTableRow(data, tableId) {
		const oldRow = this.getRowById(data.id, tableId)

		if (oldRow) {
			const rowIndex = Array.from(oldRow.parentNode.children).indexOf(oldRow)
			const parent = oldRow.parentNode

			oldRow.outerHTML = data.html

			const updatedRow = parent.children[rowIndex]

			if (updatedRow) {
				updatedRow.setAttribute('data-id', data.id)

				const allSelectedRows = document.querySelectorAll(
					'.table__row--selected'
				)
				allSelectedRows.forEach(row => {
					row.classList.remove('table__row--selected')
					const selectedCells = row.querySelectorAll('.table__cell--selected')
					selectedCells.forEach(cell =>
						cell.classList.remove('table__cell--selected')
					)
				})

				updatedRow.classList.add('table__row--selected')

				const firstCell = updatedRow.querySelector('.table__cell')
				if (firstCell) {
					firstCell.classList.add('table__cell--selected')
				}

				this.formatCurrencyValuesForRow(tableId, updatedRow)

				return updatedRow
			}
		}
	},

	async sendDeleteRequest(id, url, tableId) {
		const loader = createLoader()
		document.body.appendChild(loader)

		try {
			const response = await fetch(`${url}${id}/`, {
				method: 'POST',
				headers: {
					'X-CSRFToken': getCSRFToken(),
					'Content-Type': 'application/json',
				},
			})

			if (!response.ok) {
				const error = await response.json()
				throw new Error(error.message || 'Form submission failed')
			}

			const row = this.getRowById(id, tableId)

			if (row) {
				row.remove()
				const table = document.getElementById(tableId)
				if (table) {
					table
						.querySelectorAll('.table__row--selected, .table__cell--selected')
						.forEach(el => el.classList.remove('selected'))
					table
						.querySelector('.table__row')
						?.classList.add('table__row--selected')
					table
						.querySelector('.table__row .table__cell')
						?.classList.add('table__cell--selected')
				}

				showSuccess()
			}

			const data = await response.json()
			if (data) return data
		} catch (error) {
			console.error('Delete request failed:', error)
			showError(error.message)
		} finally {
			loader.remove()
		}
	},

	removeRow(id, tableId) {
		const row = this.getRowById(id, tableId)
		if (row) {
			row.classList.add('fade-out')
			setTimeout(() => {
				row.remove()
				this.setInitialSelectionForTable(tableId)
			}, 300)
		}
	},

	attachRowCellHandlers(row) {
		row.querySelectorAll('.table__cell').forEach(cell => {
			cell.addEventListener('click', this.onTableCellClick.bind(this))
		})
	},

	replaceTableContent(htmlContent, tableId) {
		const table = document.getElementById(tableId)
		const hiddenColumns = Array.from(table.querySelectorAll('col')).reduce(
			(acc, col, index) => {
				if (col.classList.contains('hidden')) acc.push(index)
				return acc
			},
			[]
		)

		const tableBody = document.querySelector(`#${tableId} .table__body`)
		if (tableBody) {
			tableBody.innerHTML = htmlContent
			const newTable = document.getElementById(tableId)
			hiddenColumns.forEach(index => {
				newTable
					.querySelector(`col:nth-child(${index + 1})`)
					?.classList.add('hidden')
				newTable
					.querySelector(`th:nth-child(${index + 1})`)
					?.classList.add('hidden')
				newTable.querySelectorAll(`tbody tr`).forEach(row => {
					row
						.querySelector(`td:nth-child(${index + 1})`)
						?.classList.add('hidden')
				})
			})
		} else {
			console.error(
				`Table body with id "${tableId}" not found in the provided HTML.`
			)
		}
	},

	replaceEntireTable(htmlContent, containerId, tableId) {
		const container = document.getElementById(containerId)

		if (!container) {
			console.error(`Container with id "${containerId}" not found.`)
			return
		}

		container.innerHTML = ''

		const tempDiv = document.createElement('div')
		tempDiv.innerHTML = htmlContent.trim()

		const newTableContainer = tempDiv.querySelector('.table-container')
		const newTable = tempDiv.querySelector('.table')
		if (!newTableContainer) {
			console.error('No table found in the provided HTML content.')
			container.innerHTML = htmlContent
			return
		}

		newTable.id = tableId
		container.appendChild(newTableContainer)

		this.reinitializeTable(tableId)
		this.setInitialCellSelection()
		this.attachGlobalCellClickHandler()

		return newTableContainer
	},

	getSelectedRowId(tableId) {
		const table = document.getElementById(tableId)
		if (!table) return

		const selectedRow = table.querySelector('.table__row--selected')
		if (!selectedRow) return

		const data_id = selectedRow.getAttribute('data-id')
		if (data_id !== null) {
			return data_id
		}

		const idCell = selectedRow.querySelector('td:first-child')
		return idCell?.textContent.trim()
	},

	getRowById(id, tableId) {
		const table = document.getElementById(tableId)

		if (!table) return null

		const rowByAttr = table.querySelector(`.table__row[data-id="${id}"]`)
		if (rowByAttr) {
			return rowByAttr
		}

		const rows = table.querySelectorAll('.table__row')
		return Array.from(rows).find(row => {
			const idCell = row.querySelector('td:first-child')
			return idCell?.textContent.trim() === id.toString()
		})
	},

	getSelectedRow(tableId) {
		const table = document.getElementById(tableId)
		if (!table) return null

		return table.querySelector('.table__row--selected')
	},

	async createForm(formId, tableId, rowId = null) {
		const table = document.getElementById(tableId)
		if (!table) return

		this.hideForm(formId, tableId)
		const resizableTable = this.tables.get(tableId)

		if (resizableTable) {
			let targetRow = rowId ? this.getRowById(rowId, tableId) : null
			await resizableTable.createForm(formId, rowId, targetRow)
			if (!rowId) {
				const formButtons =
					table.parentElement.querySelector('.create-form__buttons--bottom') ||
					table.parentElement.querySelector('.create-form')
				formButtons?.scrollIntoView({ behavior: 'smooth', block: 'end' })
			}
		}
	},

	hideForm(formId, tableId) {
		const table = document.getElementById(tableId)
		if (!table) return

		DOM_HELPER.removeElement(document.getElementById(formId))
	},

	async createColumnsForTable(tableId, columnConfigs, summaryOptions = null) {
		const table = document.getElementById(tableId)
		if (!table) {
			console.error(`Таблица с id "${tableId}" не найдена.`)
			return
		}

		const resizableTable = this.tables.get(tableId)
		if (!resizableTable) {
			console.error('ResizableTable instance not found.')
			return
		}

		const headerCells = Array.from(table.querySelectorAll('th'))
		const formColumnsContainer = document.createElement('tr')
		const newHeaderCells = []

		let validSummaryOptions = null
		if (summaryOptions) {
			if (Array.isArray(summaryOptions)) {
				validSummaryOptions = {
					columns: summaryOptions,
					className: null,
				}
			} else if (typeof summaryOptions === 'object') {
				validSummaryOptions = {
					columns: Array.isArray(summaryOptions.columns)
						? summaryOptions.columns
						: [],
					className: summaryOptions.className,
				}
			}

			if (validSummaryOptions && validSummaryOptions.columns.length > 0) {
				const columnNames = headerCells.map(header => header.dataset.name)
				validSummaryOptions.columns = validSummaryOptions.columns.filter(
					colName => columnNames.includes(colName)
				)
			}
		}

		for (let i = 0; i < headerCells.length; i++) {
			const th = headerCells[i]
			const colName = th.getAttribute('data-name')

			const td = document.createElement('td')
			td.className = 'table__cell-header table__filter-cell'

			const columnConfig = columnConfigs.find(config => config.name === colName)

			if (columnConfig) {
				const formBuilder = new FormBuilder(
					table,
					resizableTable.columnWidths,
					headerCells
				)

				const inputElement = await formBuilder.createColumnInput(th, i)

				if (columnConfig.url) {
					SelectHandler.setupSelects({
						url: columnConfig.url,
						select: inputElement,
					})
				}

				this.addFilterHandler(inputElement, table, i, validSummaryOptions)
				td.appendChild(inputElement)
			}

			formColumnsContainer.appendChild(td)
			newHeaderCells.push(td)
		}

		const thead = table.querySelector('thead')
		thead.appendChild(formColumnsContainer)

		this.applyMaxWidthToNewHeaders(newHeaderCells, resizableTable)
	},

	applyMaxWidthToNewHeaders(newHeaderCells, resizableTable) {
		newHeaderCells.forEach((headerCell, index) => {
			const width =
				resizableTable.columnWidths[index] || resizableTable.minColumnWidth
			headerCell.style.maxWidth = `${width}px`
		})
	},

	addFilterHandler(inputElement, table, columnIndex, summaryOptions = null) {
		const tableId = table.id
		const filters = this.getTableFilters(tableId)

		const updateSummary = () => {
			if (summaryOptions?.columns?.length > 0) {
				this.calculateTableSummary(tableId, summaryOptions.columns, {
					className: summaryOptions.className,
				})
			}
		}

		if (inputElement.classList.contains('select')) {
			const selectControl = inputElement.querySelector('.select__control')
			const dropdown = inputElement.querySelector('.select__dropdown')
			const clearButton = inputElement.querySelector('.select__clear')

			if (!selectControl || !dropdown || !clearButton) return

			selectControl.addEventListener('click', () => {
				const observer = new MutationObserver(() => {
					const dropdownOptions = dropdown.querySelectorAll('.select__option')

					dropdownOptions.forEach(option => {
						option.addEventListener('click', () => {
							const filterText = option.textContent.toLowerCase()
							filters.set(columnIndex, {
								type: 'select',
								value: filterText,
							})
							this.applyFilters(table, filters)
							updateSummary()
						})
					})

					observer.disconnect()
				})

				observer.observe(dropdown, { childList: true })
			})

			clearButton.addEventListener('click', () => {
				const selectInput = inputElement.querySelector('.select__input')
				const selectText = inputElement.querySelector('.select__text')

				selectInput.value = ''
				selectText.textContent = ''
				filters.delete(columnIndex)
				this.applyFilters(table, filters)
				updateSummary()
			})
		} else {
			const input = inputElement.querySelector('input')
			const clearButton = inputElement.querySelector('.clear-button')

			if (!input || !clearButton) return

			input.addEventListener('input', () => {
				const filterValue = input.value.toLowerCase()
				if (filterValue) {
					filters.set(columnIndex, {
						type: 'text',
						value: filterValue,
					})
				} else {
					filters.delete(columnIndex)
				}
				this.applyFilters(table, filters)
				updateSummary()
			})

			clearButton.addEventListener('click', () => {
				input.value = ''
				input.focus()
				filters.delete(columnIndex)
				this.applyFilters(table, filters)
				updateSummary()
			})
		}
	},

	getTableFilters(tableId) {
		if (!this.tableFilters.has(tableId)) {
			this.tableFilters.set(tableId, new Map())
		}
		return this.tableFilters.get(tableId)
	},

	applyFilters(table, filters) {
		const tbody = table.querySelector('tbody')

		Array.from(tbody.querySelectorAll('tr')).forEach(row => {
			if (row.classList.contains('table__row--summary')) return

			let shouldShow = true

			filters.forEach((filterValue, colIndex) => {
				const cell = row.querySelector(`td:nth-child(${colIndex + 1})`)
				if (!cell) return

				const cellText = cell.textContent.trim().toLowerCase()

				if (filterValue.type === 'select') {
					shouldShow = shouldShow && cellText === filterValue.value
				} else {
					shouldShow = shouldShow && cellText.includes(filterValue.value)
				}
			})

			row.style.display = shouldShow ? '' : 'none'
		})
	},

	destroyTables() {
		this.tables.forEach(table => table.destroy())
		this.tables.clear()
		this.tableFilters.clear()
	},

	calculateTableSummary(
		tableId,
		columnsToSum,
		options = { grouped: false, total: true, className: null, ids: null }
	) {
		if (
			!columnsToSum ||
			!Array.isArray(columnsToSum) ||
			columnsToSum.length === 0
		) {
			console.warn(`No columns to sum specified for table "${tableId}"`)
			return
		}

		const table = document.getElementById(tableId)
		if (!table) return

		const tbody = table.querySelector('tbody')
		if (!tbody) return

		tbody.querySelectorAll('.table__row--summary').forEach(row => row.remove())

		const headers = Array.from(table.querySelectorAll('thead th'))
		const columnNames = headers.map(header => header.dataset.name)

		const groupRows = Array.from(tbody.querySelectorAll('.table__group-row'))

		const filterRowsByIds = (rows, ids) => {
			if (!Array.isArray(ids) || ids.length === 0) return rows
			const idsStr = ids.map(String)
			return rows.filter(row => idsStr.includes(row.getAttribute('data-id')))
		}

		if (options.grouped && groupRows.length > 0) {
			groupRows.forEach(groupRow => {
				let currentRow = groupRow.nextElementSibling
				const rows = []

				while (
					currentRow &&
					!currentRow.classList.contains('table__group-row')
				) {
					if (
						!currentRow.classList.contains('table__row--summary') &&
						currentRow.style.display !== 'none'
					) {
						rows.push(currentRow)
					}
					currentRow = currentRow.nextElementSibling
				}

				const filteredRows = filterRowsByIds(rows, options.ids)

				if (filteredRows.length > 0) {
					const summaryData = this.calculateSums(
						filteredRows,
						columnsToSum,
						columnNames
					)
					const summaryRow = this.createSummaryRow(
						headers,
						columnNames,
						summaryData,
						'text-blue'
					)
					const lastRow = filteredRows[filteredRows.length - 1]
					this.applyColumnWidthsForRow(tableId, summaryRow)

					tbody.insertBefore(summaryRow, lastRow.nextElementSibling)
				}
			})
		}

		if (!options.grouped || options.total) {
			let rows = Array.from(
				tbody.querySelectorAll(
					'tr:not(.table__row--summary):not(.table__group-row)'
				)
			).filter(row => row.style.display !== 'none')

			rows = filterRowsByIds(rows, options.ids)

			if (rows.length > 0) {
				const summaryData = this.calculateSums(rows, columnsToSum, columnNames)
				const summaryRow = this.createSummaryRow(
					headers,
					columnNames,
					summaryData,
					options.className
				)

				this.applyColumnWidthsForRow(tableId, summaryRow)

				tbody.appendChild(summaryRow)
			}
		}
	},

	calculateSums(rows, columnsToSum, columnNames) {
		const summaryData = {}

		columnsToSum.forEach(columnName => {
			const columnIndex = columnNames.indexOf(columnName)
			if (columnIndex === -1) return

			const sum = rows.reduce((acc, row) => {
				const cell = row.cells[columnIndex]
				if (cell) {
					const rawValue = cell.textContent.trim().replace(/[^\d,-]/g, '')
					const value = parseFloat(rawValue.replace(',', '.'))
					if (!isNaN(value)) {
						return acc + value
					}
				}
				return acc
			}, 0)

			summaryData[columnName] = sum.toFixed(0).replace('.', ',')
		})

		return summaryData
	},

	createSummaryRow(headers, columnNames, summaryData, className) {
		const row = document.createElement('tr')
		row.className = 'table__row table__row--summary'

		headers.forEach((header, colIndex) => {
			const isHidden = header.classList.contains('hidden')

			const cell = document.createElement('td')
			cell.className = 'table__cell'

			if (isHidden) {
				cell.classList.add('hidden')
			}

			const columnName = columnNames[colIndex]
			if (summaryData[columnName] !== undefined) {
				cell.classList.add('table__cell--summary')

				const formattedValue = this.formatNumber(summaryData[columnName])
				cell.textContent = `${formattedValue} р.`

				if (className) {
					cell.classList.add(className)
				} else {
					const value = parseFloat(summaryData[columnName].replace(',', '.'))
					if (value >= 0) {
						cell.classList.add('text-green')
					} else {
						cell.classList.add('text-red')
					}
				}
			}

			row.appendChild(cell)
		})

		return row
	},

	addActionsColumn(tableId, ids, onEdit, onDelete) {
		const table = document.getElementById(tableId)
		if (!table) {
			console.error(`Table with id "${tableId}" not found.`)
			return
		}

		const tbody = table.querySelector('tbody')
		if (!tbody) {
			console.error(`Table body not found for table with id "${tableId}".`)
			return
		}

		const headers = table.querySelector('thead tr')
		if (!headers) {
			console.error(`Table header not found in table with id "${tableId}".`)
			return
		}

		const actionHeader = document.createElement('th')
		actionHeader.className = 'table__cell-header table__header--actions'
		headers.appendChild(actionHeader)

		const rows = Array.from(tbody.querySelectorAll('tr'))
		rows.forEach((row, index) => {
			if (row.classList.contains('table__row--summary')) {
				return
			}

			const id = ids[index]
			row.setAttribute('data-id', id)

			const actionCell = document.createElement('td')
			actionCell.className = 'table__cell table__cell--actions'

			const editButton = document.createElement('button')
			const editIcon = document.createElement('i')
			editIcon.className = 'fas fa-edit'
			editButton.appendChild(editIcon)
			editButton.className = 'table__header--action-edit'
			editButton.addEventListener('click', event => {
				event.stopPropagation()
				const id = ids[index]

				onEdit(id, row, tableId)
			})

			const deleteButton = document.createElement('button')
			const deleteIcon = document.createElement('i')
			deleteIcon.className = 'fas fa-times'
			deleteButton.appendChild(deleteIcon)
			deleteButton.className = 'table__header--action-delete'
			deleteButton.addEventListener('click', event => {
				event.stopPropagation()
				const id = ids[index]

				onDelete(id, row, tableId)
			})

			actionCell.appendChild(editButton)
			actionCell.appendChild(deleteButton)

			row.appendChild(actionCell)
		})
	},

	addActionsToRow(row, id, onEdit, onDelete) {
		if (row.classList.contains('table__row--summary')) {
			return
		}

		const actionCell = document.createElement('td')
		actionCell.className = 'table__cell table__cell--actions'

		const editButton = document.createElement('button')
		const editIcon = document.createElement('i')
		editIcon.className = 'fas fa-edit'
		editButton.appendChild(editIcon)
		editButton.className = 'table__header--action-edit'
		editButton.addEventListener('click', event => {
			event.stopPropagation()
			onEdit(id, row, row.closest('.table').id)
		})

		const deleteButton = document.createElement('button')
		const deleteIcon = document.createElement('i')
		deleteIcon.className = 'fas fa-times'
		deleteButton.appendChild(deleteIcon)
		deleteButton.className = 'table__header--action-delete'
		deleteButton.addEventListener('click', event => {
			event.stopPropagation()

			onDelete(id, row, row.closest('.table').id)
		})

		actionCell.appendChild(editButton)
		actionCell.appendChild(deleteButton)

		row.appendChild(actionCell)
	},

	formatNumber(num) {
		return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
	},
}

document.addEventListener('DOMContentLoaded', function () {
	const navList = document.querySelector('.nav-list')
	if (navList) {
		const itemsCount = navList.children.length
		if (itemsCount === 7) {
			navList.style.gridTemplateColumns = 'repeat(4, minmax(0, 1fr))'
		} else {
			navList.style.gridTemplateColumns = 'repeat(5, minmax(0, 1fr))'
		}
	}

	// function resizeCharts() {
	// 	const statsChart = document.getElementById('statsChart')
	// 	const profitChart = document.getElementById('profitChart')
	// 	if (!statsChart || !profitChart) return
	// 	const w = statsChart.parentElement.offsetWidth
	// 	let h = 264
	// 	let profitW = 40
	// 	if (window.innerWidth <= 600) {
	// 		h = 200
	// 		profitW = 35
	// 	} else if (window.innerWidth <= 1024) {
	// 		h = 180
	// 	}
	// 	statsChart.width = w
	// 	statsChart.height = h
	// 	profitChart.width = profitW
	// 	profitChart.height = h

	// 	if (window.capitalChart) {
	// 		window.capitalChart.destroy()
	// 		window.capitalChart = null
	// 	}
	// 	if (window.profitChartInstance) {
	// 		window.profitChartInstance.destroy()
	// 		window.profitChartInstance = null
	// 	}
	// 	if (window.drawCharts) {
	// 		window.drawCharts()
	// 	}
	// }
	// window.addEventListener('resize', resizeCharts)
	// resizeCharts()
})
