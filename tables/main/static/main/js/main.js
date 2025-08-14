import { DynamicFormHandler } from '/static/js/dynamicFormHandler.js'
import { TableManager } from '/static/js/table.js'
import { initTableHandlers } from '/static/js/tableHandlers.js'
import { createLoader, getCSRFToken, showError } from '/static/js/ui-utils.js'

const TRANSACTION = 'transactions'
const SUPPLIERS = 'suppliers'
const CLIENTS = 'clients'
const CASH_FLOW = 'cash_flow'
const MONEY_TRANSFERS = 'money_transfers'

const BASE_URL = '/'
const CURRENCY_SUFFIX = ' р.'

const fetchData = async url => {
	try {
		const response = await fetch(url)

		if (!response.ok) {
			const errorText = await response.json()
			throw new Error(`${errorText.message}`)
		}
		return await response.json()
	} catch (error) {
		console.error('Fetch error:', error)
		showError(error.message || 'Ошибка при загрузке данных.')
		throw error
	}
}

const postData = async (url, data) => {
	try {
		const response = await fetch(url, {
			method: 'POST',
			headers: {
				'X-CSRFToken': getCSRFToken(),
				'Content-Type': 'application/json',
			},
			body: JSON.stringify(data),
		})
		if (!response.ok) {
			throw new Error(`HTTP error! status: ${response.status}`)
		}
		return await response.json()
	} catch (error) {
		console.error('Post error:', error)
		showError(error.message || 'Ошибка при отправке данных.')
		throw error
	}
}

const setupCurrencyInput = inputId => {
	const input = document.getElementById(inputId)
	if (!input) {
		console.error(`Input with id "${inputId}" not found`)
		return null
	}

	if (input.autoNumeric) {
		input.autoNumeric.remove()
	}

	const anElement = new AutoNumeric(input, {
		allowDecimalPadding: true,
		alwaysAllowDecimalCharacter: true,
		currencySymbol: CURRENCY_SUFFIX,
		currencySymbolPlacement: 's',
		decimalPlacesRawValue: 0,
		decimalPlaces: 0,
		digitGroupSeparator: ' ',
		emptyInputBehavior: 'null',
		minimumValue: '0',
		allowEmpty: true,
	})

	input.autoNumeric = anElement

	return anElement
}

const setupPercentInput = inputId => {
	const input = document.getElementById(inputId)
	if (!input) {
		console.error(`Input with id "${inputId}" not found`)
		return null
	}

	if (input.autoNumeric) {
		input.autoNumeric.remove()
	}

	const anElement = new AutoNumeric(input, {
		allowDecimalPadding: true,
		alwaysAllowDecimalCharacter: true,
		currencySymbol: '%',
		currencySymbolPlacement: 's',
		decimalPlacesRawValue: 1,
		decimalPlaces: 1,
		digitGroupSeparator: '',
		emptyInputBehavior: 'null',
		minimumValue: '0',
		maximumValue: '100',
		allowEmpty: true,
	})

	input.autoNumeric = anElement

	return anElement
}

const colorizeAmounts = tableId => {
	const table = document.getElementById(tableId)
	if (!table) return

	const headers = table.querySelectorAll('thead th')
	let amountColumnIndex = -1

	headers.forEach((header, index) => {
		if (header.dataset.name === 'formatted_amount') {
			amountColumnIndex = index
		}
	})

	if (amountColumnIndex === -1) return

	const rows = table.querySelectorAll('tbody tr')
	rows.forEach(row => {
		const cell = row.querySelectorAll('td')[amountColumnIndex]
		if (!cell) return

		const value = cell.textContent.trim()
		if (value.startsWith('-')) {
			cell.classList.add('text-red')
		} else if (value !== '0 р.' && value !== '0,00 р.') {
			cell.classList.add('text-green')
		}
	})
}

const selectOptionById = (selectId, valueToSelect) => {
	const selectInput = document.getElementById(selectId)
	if (!selectInput) {
		console.error(`Селект с ID "${selectId}" не найден`)
		return false
	}

	const selectContainer = selectInput.closest('.select')
	if (!selectContainer) {
		console.error(`Контейнер .select не найден для селекта "${selectId}"`)
		return false
	}

	const dropdown = selectContainer.querySelector('.select__dropdown')
	if (!dropdown) {
		console.error(
			`Выпадающий список .select__dropdown не найден для селекта "${selectId}"`
		)
		return false
	}

	const option = dropdown.querySelector(
		`.select__option[data-value="${valueToSelect}"]`
	)
	if (!option) {
		console.error(
			`Опция с data-value="${valueToSelect}" не найдена в селекте "${selectId}"`
		)
		return false
	}

	const selectedText = selectContainer.querySelector(
		'.select__control .select__text'
	)
	selectInput.value = valueToSelect

	if (selectedText) {
		selectedText.textContent = option.textContent.trim()
		selectedText.classList.remove('select__placeholder')
	}

	const event = new Event('change', { bubbles: true })
	selectInput.dispatchEvent(event)
	return true
}

const setIds = (ids, tableId) => {
	const tableRows = document.querySelectorAll(
		`#${tableId} tbody tr:not(.table__row--summary)`
	)
	if (!tableRows || tableRows.length === 0 || !ids || ids.length === 0) {
		return
	}
	if (tableRows.length !== ids.length) {
		console.error('Количество строк не совпадает с количеством ID')
	} else {
		tableRows.forEach((row, index) => {
			row.setAttribute('data-id', ids[index])
		})
	}
}

const setColumnIds = (ids, tableId) => {
	const headerCells = document.querySelectorAll(`#${tableId} thead th`)
	const columnsToProcess = headerCells.length - 2

	if (columnsToProcess !== ids.length) {
		console.error(
			`Количество столбцов (${columnsToProcess}) не совпадает с количеством ID (${ids.length})`
		)
		return
	}

	for (let colIndex = 1; colIndex < headerCells.length - 1; colIndex++) {
		const idIndex = colIndex - 1
		const columnId = ids[idIndex]
		headerCells[colIndex].setAttribute('data-account-id', columnId)
	}

	const rows = document.querySelectorAll(`#${tableId} tbody tr`)
	rows.forEach(row => {
		const cells = row.querySelectorAll('td')
		for (let colIndex = 1; colIndex < cells.length - 1; colIndex++) {
			if (colIndex >= cells.length) continue
			const idIndex = colIndex - 1
			if (idIndex >= ids.length) continue
			const columnId = ids[idIndex]
			cells[colIndex].setAttribute('data-account-id', columnId)
		}
	})
}

const getSelectedAccountId = tableId => {
	const table = document.getElementById(tableId)
	if (!table) return null

	const selectedCell = table.querySelector('.table__cell--selected')
	if (selectedCell) {
		return selectedCell.getAttribute('data-account-id')
	}

	const selectedRow = table.querySelector('.table__row--selected')
	if (!selectedRow) return null

	const activeCell = document.activeElement
	if (
		activeCell &&
		activeCell.tagName.toLowerCase() === 'td' &&
		selectedRow.contains(activeCell)
	) {
		const cellIndex = Array.from(selectedRow.cells).indexOf(activeCell)
		if (cellIndex > 0 && cellIndex < selectedRow.cells.length - 1) {
			return (
				activeCell.getAttribute('data-account-id') ||
				table
					.querySelector(`thead th:nth-child(${cellIndex + 1})`)
					.getAttribute('data-account-id')
			)
		}
	}

	return null
}

const setLastRowId = (id, tableId) => {
	const tableRows = Array.from(
		document.querySelectorAll(`#${tableId} tbody tr:not(.table__row--summary)`)
	)
	if (tableRows.length === 0) {
		console.error(`Таблица ${tableId} не содержит строк`)
		return
	}

	const lastRow = tableRows[tableRows.length - 1]
	lastRow.setAttribute('data-id', id)
}

const showChangedCells = (changedCells, tableId) => {
	const headers = document.querySelectorAll(`#${tableId} thead th`)
	const columnIndexes = {}

	headers.forEach((header, index) => {
		const name = header.dataset.name
		if (name) {
			columnIndexes[name] = index
		}
	})

	document.querySelectorAll(`#${tableId} tbody tr`).forEach(row => {
		const rowId = row.dataset.id
		const cellInfo = changedCells[rowId]
		const cells = row.querySelectorAll('td')

		if (cellInfo) {
			if (
				cellInfo.client_percentage &&
				columnIndexes.client_percentage !== undefined
			) {
				cells[columnIndexes.client_percentage].classList.add(
					'table__cell--changed'
				)
			}
			if (
				cellInfo.supplier_percentage &&
				columnIndexes.supplier_percentage !== undefined
			) {
				cells[columnIndexes.supplier_percentage].classList.add(
					'table__cell--changed'
				)
			}
		}
	})
}

const hideCompletedTransactions = supplierDebts => {
	const table = document.getElementById(`${TRANSACTION}-table`)
	if (!table) return

	const headers = table.querySelectorAll('thead th')
	let debtColumnIndex = -1
	let docsColumnIndex = -1

	headers.forEach((header, index) => {
		if (header.dataset.name === 'debt') {
			debtColumnIndex = index
		} else if (header.dataset.name === 'documents') {
			docsColumnIndex = index
		}
	})

	if (debtColumnIndex === -1 || docsColumnIndex === -1) return

	const rows = table.querySelectorAll('tbody tr:not(.table__row--summary)')
	rows.forEach((row, idx) => {
		const debtCell = row.querySelectorAll('td')[debtColumnIndex]
		const docsCell = row.querySelectorAll('td')[docsColumnIndex]

		if (!debtCell || !docsCell) return

		const debtValue = debtCell.textContent.trim()
		const docsChecked =
			docsCell.querySelector('input[type="checkbox"]')?.checked ||
			docsCell.querySelector('.checkbox--checked') !== null

		const supplierDebt =
			supplierDebts && supplierDebts[idx] !== undefined
				? supplierDebts[idx]
				: null
		const isSupplierDebtZero =
			supplierDebt === 0 ||
			supplierDebt === '0' ||
			supplierDebt === '0 р.' ||
			supplierDebt === '0,00 р.'

		if (
			(debtValue === '0 р.' || debtValue === '0,00 р.') &&
			docsChecked &&
			isSupplierDebtZero
		) {
			row.classList.add('hidden-row', 'row-done')
		}
	})

	updateHiddenRowsCounter()
}

const toggleTransactionVisibility = rowId => {
	const row = document.querySelector(
		`#${TRANSACTION}-table tr[data-id="${rowId}"]`
	)
	if (!row) return

	row.classList.toggle('hidden-row')
	updateHiddenRowsCounter()
}

const toggleAllTransactions = (show, supplierDebts) => {
	const table = document.getElementById(`${TRANSACTION}-table`)
	if (!table) return

	const rows = document.querySelectorAll(
		`#${TRANSACTION}-table tbody tr:not(.table__row--summary)`
	)

	if (show) {
		rows.forEach(row => {
			row.classList.remove('hidden-row')
		})
	} else {
		const headers = table.querySelectorAll('thead th')
		let debtColumnIndex = -1
		let docsColumnIndex = -1

		headers.forEach((header, index) => {
			if (header.dataset.name === 'debt') {
				debtColumnIndex = index
			} else if (header.dataset.name === 'documents') {
				docsColumnIndex = index
			}
		})

		if (debtColumnIndex === -1 || docsColumnIndex === -1) return

		rows.forEach((row, idx) => {
			const debtCell = row.querySelectorAll('td')[debtColumnIndex]
			const docsCell = row.querySelectorAll('td')[docsColumnIndex]

			if (!debtCell || !docsCell) return

			const debtValue = debtCell.textContent.trim()
			const docsChecked =
				docsCell.querySelector('input[type="checkbox"]')?.checked ||
				docsCell.querySelector('.checkbox--checked') !== null

			const supplierDebt =
				supplierDebts && supplierDebts[idx] !== undefined
					? supplierDebts[idx]
					: null
			const isSupplierDebtZero =
				supplierDebt === 0 ||
				supplierDebt === '0' ||
				supplierDebt === '0 р.' ||
				supplierDebt === '0,00 р.'

			if (
				(debtValue === '0 р.' || debtValue === '0,00 р.') &&
				docsChecked &&
				isSupplierDebtZero
			) {
				row.classList.add('hidden-row')
			}
		})
	}

	updateHiddenRowsCounter()
}

const updateHiddenRowsCounter = () => {
	const hiddenCount = document.querySelectorAll(
		`#${TRANSACTION}-table .hidden-row`
	).length
	const totalCount = document.querySelectorAll(
		`#${TRANSACTION}-table tbody tr:not(.table__row--summary)`
	).length
	const counterElement = document.getElementById('hidden-rows-counter')

	if (counterElement) {
		if (hiddenCount > 0) {
			counterElement.textContent = `Скрыто: ${hiddenCount} из ${totalCount}`
			counterElement.style.display = 'block'
		} else {
			counterElement.style.display = 'none'
		}
	} else if (hiddenCount > 0) {
		const counter = document.createElement('div')
		counter.id = 'hidden-rows-counter'
		counter.className = 'hidden-rows-counter'
		counter.textContent = `Скрыто: ${hiddenCount} из ${totalCount}`
		const tableContainer = document.getElementById(`${TRANSACTION}-container`)
		if (tableContainer) {
			tableContainer.appendChild(counter)
		}
	}
}

const addMenuHandler = () => {
	const menu = document.getElementById('context-menu')
	const addButton = document.getElementById('add-button')
	const editButton = document.getElementById('edit-button')
	const deleteButton = document.getElementById('delete-button')
	const paymentButton = document.getElementById('payment-button')
	const hideButton = document.getElementById('hide-button')
	const settleDebtButton = document.getElementById('settle-debt-button')

	function showMenu(x, y) {
		menu.style.display = 'block'
		menu.style.left = `${x + 10}px`
		menu.style.top = `${y}px`
	}

	if (menu) {
		document.addEventListener('contextmenu', function (e) {
			const row = e.target.closest(
				'tbody tr:not(.table__row--summary):not(.table__row--empty)'
			)
			const table = e.target.closest('table')

			if (row && table) {
				e.preventDefault()

				if (addButton) addButton.style.display = 'block'
				if (editButton) editButton.style.display = 'block'
				if (deleteButton) deleteButton.style.display = 'block'
				if (paymentButton) paymentButton.style.display = 'block'
				if (hideButton) hideButton.style.display = 'block'
				if (settleDebtButton) settleDebtButton.style.display = 'block'

				showMenu(e.pageX, e.pageY)
				return
			}

			if (e.target.closest('.content')) {
				e.preventDefault()

				if (addButton) addButton.style.display = 'block'
				if (editButton) editButton.style.display = 'none'
				if (deleteButton) deleteButton.style.display = 'none'
				if (paymentButton) paymentButton.style.display = 'none'
				if (hideButton) hideButton.style.display = 'none'
				if (settleDebtButton) settleDebtButton.style.display = 'none'

				showMenu(e.pageX, e.pageY)
			}
		})

		document.addEventListener('click', () => {
			menu.style.display = 'none'
		})
	}
}

const markAsViewed = async (id, row) => {
	try {
		const response = await postData(
			`${BASE_URL}${TRANSACTION}/${id}/mark-viewed/`,
			{}
		)

		if (response.ok) {
			row.classList.remove('table__row--blinking')
			const markReadBtn = row.querySelector('.mark-read-btn')
			if (markReadBtn) {
				markReadBtn.remove()
			}

			const blinkingRows = document.querySelectorAll(
				`#${TRANSACTION}-table .table__row--blinking`
			)
			if (blinkingRows.length === 0) {
				const markAllBtn = document.getElementById('mark-all-read-btn')
				if (markAllBtn) markAllBtn.remove()
			}
		} else {
			const data = await response.json()
			showError(data.message || 'Ошибка при отметке транзакции как прочитанной')
		}
	} catch (error) {
		console.error('Ошибка при отметке транзакции:', error)
		showError('Ошибка при отметке транзакции как прочитанной')
	}
}

const markAllAsViewed = async () => {
	const blinkingRows = document.querySelectorAll(
		`#${TRANSACTION}-table .table__row--blinking`
	)
	if (blinkingRows.length === 0) return

	const loader = createLoader()
	document.body.appendChild(loader)

	try {
		const ids = []
		const rows = {}

		blinkingRows.forEach(row => {
			const id = row.getAttribute('data-id')
			if (id) {
				ids.push(id)
				rows[id] = row
			}
		})

		const response = await postData(
			`${BASE_URL}${TRANSACTION}/mark-all-viewed/`,
			{ ids }
		)

		if (response.ok) {
			blinkingRows.forEach(row => {
				row.classList.remove('table__row--blinking')
				const markReadBtn = row.querySelector('.mark-read-btn')
				if (markReadBtn) {
					markReadBtn.remove()
				}
			})

			const markAllBtn = document.getElementById('mark-all-read-btn')
			if (markAllBtn) markAllBtn.remove()
		} else {
			const data = await response.json()
			showError(data.message || 'Ошибка при отметке транзакций как прочитанных')
		}
	} catch (error) {
		console.error('Ошибка при отметке всех транзакций:', error)
		showError('Ошибка при отметке транзакций как прочитанных')
	} finally {
		loader.remove()
	}
}

const highlightModifiedRows = async () => {
	try {
		const data = await fetchData(`${BASE_URL}${TRANSACTION}/modified/`)
		const modifiedIds = data.modified_ids

		if (modifiedIds.length > 0) {
			const tableContainer = document.querySelector(`#${TRANSACTION}-container`)
			let markAllBtn = document.getElementById('mark-all-read-btn')

			if (!markAllBtn && tableContainer) {
				markAllBtn = document.createElement('button')
				markAllBtn.id = 'mark-all-read-btn'
				markAllBtn.className = 'mark-all-read-btn mark-read-btn'
				markAllBtn.title = 'Отметить все как прочитанные'
				markAllBtn.innerHTML =
					'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"></path></svg>'
				markAllBtn.addEventListener('click', markAllAsViewed)

				const table = document.getElementById(`${TRANSACTION}-table`)
				table.appendChild(markAllBtn)
			}
		}

		modifiedIds.forEach(id => {
			const row = document.querySelector(
				`#${TRANSACTION}-table tr[data-id="${id}"]`
			)
			if (row) {
				row.classList.add('table__row--blinking')

				const markReadBtn = document.createElement('button')
				markReadBtn.className = 'mark-read-btn'
				markReadBtn.title = 'Отметить как прочитанное'
				markReadBtn.innerHTML =
					'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"></path></svg>'
				markReadBtn.style.position = 'absolute'
				markReadBtn.style.right = '0px'
				markReadBtn.style.top = '50%'
				markReadBtn.style.transform = 'translateY(-50%)'
				markReadBtn.addEventListener('click', function (e) {
					e.stopPropagation()
					markAsViewed(id, row)
				})

				if (getComputedStyle(row).position === 'static') {
					row.style.position = 'relative'
				}
				row.appendChild(markReadBtn)
			}
		})
	} catch (error) {
		console.error('Ошибка при получении измененных транзакций:', error)
		showError('Не удалось получить измененные транзакции.')
	}
}

const checkOperationType = () => {
	const operationTypeInput = document.getElementById('operation_type')
	const purposeField = document.getElementById('purpose')?.closest('.select')

	if (operationTypeInput && purposeField) {
		const togglePurposeVisibility = () => {
			purposeField.style.display =
				operationTypeInput.value === 'income' ? 'none' : ''
		}

		togglePurposeVisibility()
		operationTypeInput.addEventListener('change', togglePurposeVisibility)
	}
}

const setupSelectListener = () => {
	document.addEventListener('click', async function (e) {
		if (e.target && e.target.classList.contains('select__option')) {
			const dropdown = e.target.closest('.select__dropdown')
			if (!dropdown) return

			const selectContainer = dropdown.parentElement
			const clientInput = selectContainer.querySelector('input#client')
			const supplierInput = selectContainer.querySelector('input#supplier')

			if (clientInput) {
				const optionValue = e.target.dataset.value
				try {
					const { data } = await fetchData(`${BASE_URL}clients/${optionValue}/`)
					const percentageInput = document.getElementById('client_percentage')
					if (percentageInput && data.percentage !== undefined) {
						percentageInput.value = data.percentage
						setupPercentInput('client_percentage')
					}
				} catch (error) {
					console.error('Ошибка при обработке значения клиента:', error)
					showError('Не удалось получить данные клиента.')
				}
			}

			if (supplierInput) {
				const optionValue = e.target.dataset.value
				try {
					const { data } = await fetchData(
						`${BASE_URL}${SUPPLIERS}/${optionValue}/`
					)
					const percentageInput = document.getElementById('supplier_percentage')
					if (percentageInput && data.cost_percentage !== undefined) {
						percentageInput.value = data.cost_percentage
						setupPercentInput('supplier_percentage')
					}
				} catch (error) {
					console.error('Ошибка при обработке значения поставщика:', error)
					showError('Не удалось получить данные поставщика.')
				}
			}
		}
	})
}

const refreshData = (tableId, rowId = null) => {
	if (rowId) {
		setLastRowId(rowId, `${tableId}`)
	}
}

const hideCompletedDebtors = (tableId, type) => {
	if (!tableId) return

	const table = document.getElementById(tableId)
	if (!table) return

	const headers = table.querySelectorAll('thead th')
	let debtColumnIndex = -1

	let columnName = 'supplier_debt'
	if (type === 'Бонусы' || type === 'bonus') {
		columnName = 'bonus_debt'
	} else if (type === 'Выдачи клиентам' || type === 'remaining') {
		columnName = 'client_debt'
	}

	headers.forEach((header, index) => {
		if (header.dataset.name === columnName) {
			debtColumnIndex = index
		}
	})

	if (debtColumnIndex === -1) return

	const rows = table.querySelectorAll('tbody tr:not(.table__row--summary)')
	rows.forEach(row => {
		const debtCell = row.querySelectorAll('td')[debtColumnIndex]
		if (!debtCell) return

		const debtValue = debtCell.textContent.trim()
		if (debtValue === '0 р.' || debtValue === '0,00 р.' || debtValue === '0') {
			row.classList.add('hidden-row')
		}
	})

	updateHiddenDebtorsCounter()
}

const toggleDebtorVisibility = (rowId, tableId) => {
	const row = document.querySelector(`#${tableId} tr[data-id="${rowId}"]`)
	if (!row) return

	row.classList.toggle('hidden-row')
	updateHiddenDebtorsCounter()
}

const toggleAllDebtors = (show, tableId) => {
	const table = document.getElementById(tableId)

	if (!table) return

	let columnName = 'supplier_debt'
	if (tableId === 'summary-bonus') {
		columnName = 'bonus_debt'
	} else if (tableId === 'summary-remaining') {
		columnName = 'client_debt'
	}

	const rows = document.querySelectorAll(
		`#${tableId} tbody tr:not(.table__row--summary)`
	)

	if (show) {
		rows.forEach(row => {
			row.classList.remove('hidden-row')
		})
	} else {
		const headers = table.querySelectorAll('thead th')
		let debtColumnIndex = -1

		headers.forEach((header, index) => {
			if (header.dataset.name === columnName) {
				debtColumnIndex = index
			}
		})

		if (debtColumnIndex === -1) return

		rows.forEach(row => {
			const debtCell = row.querySelectorAll('td')[debtColumnIndex]
			if (!debtCell) return

			const debtValue = debtCell.textContent.trim()
			if (
				debtValue === '0 р.' ||
				debtValue === '0,00 р.' ||
				debtValue === '0'
			) {
				row.classList.add('hidden-row')
			}
		})
	}

	updateHiddenDebtorsCounter()
}

const updateHiddenDebtorsCounter = () => {
	const hiddenCount = document.querySelectorAll(
		`#debtors-table .hidden-row`
	).length
	const totalCount = document.querySelectorAll(
		`#debtors-table tbody tr:not(.table__row--summary)`
	).length
	const counterElement = document.getElementById('hidden-rows-counter')

	if (counterElement) {
		if (hiddenCount > 0) {
			counterElement.textContent = `Скрыто: ${hiddenCount} из ${totalCount}`
			counterElement.style.display = 'block'
		} else {
			counterElement.style.display = 'none'
		}
	} else if (hiddenCount > 0) {
		const counter = document.createElement('div')
		counter.id = 'hidden-rows-counter'
		counter.className = 'hidden-rows-counter'
		counter.textContent = `Скрыто: ${hiddenCount} из ${totalCount}`
		const tableContainer =
			document.getElementById(`debtors-table`).parentElement
		if (tableContainer) {
			tableContainer.appendChild(counter)
		}
	}
}

const hideDebtorRowIfNoDebt = (row, tableId, type) => {
	const table = document.getElementById(tableId)
	if (!table || !row) return

	const headers = table.querySelectorAll('thead th')
	let debtColumnIndex = -1

	let columnName = 'supplier_debt'
	if (type === 'Бонусы' || type === 'bonus') {
		columnName = 'bonus_debt'
	} else if (type === 'Выдачи клиентам' || type === 'remaining') {
		columnName = 'client_debt'
	}

	headers.forEach((header, index) => {
		if (header.dataset.name === columnName) {
			debtColumnIndex = index
		}
	})

	if (debtColumnIndex === -1) return

	const debtCell = row.querySelectorAll('td')[debtColumnIndex]
	if (!debtCell) return

	const debtValue = debtCell.textContent.trim()
	if (debtValue === '0 р.' || debtValue === '0,00 р.' || debtValue === '0') {
		row.classList.add('hidden-row')
	} else {
		row.classList.remove('hidden-row')
	}

	updateHiddenDebtorsCounter()
}

const colorizeZeroDebts = tableId => {
	if (!tableId) return

	const table = document.getElementById(tableId)
	if (!table) return

	let columnName = 'supplier_debt'
	if (tableId === 'summary-bonus') {
		columnName = 'bonus_debt'
	} else if (tableId === 'summary-remaining') {
		columnName = 'client_debt'
	}

	const headers = table.querySelectorAll('thead th')
	let debtColumnIndex = -1

	headers.forEach((header, index) => {
		if (header.dataset.name === columnName) {
			debtColumnIndex = index
		}
	})

	if (debtColumnIndex === -1) return

	const rows = table.querySelectorAll('tbody tr')
	rows.forEach(row => {
		if (row.classList.contains('table__row--summary')) return

		const debtCell = row.querySelectorAll('td')[debtColumnIndex]
		if (!debtCell) return

		const debtValue = debtCell.textContent.trim()
		if (debtValue === '0' || debtValue === '0 р.' || debtValue === '0,00 р.') {
			row.classList.add('row-done')

			debtCell.textContent = '0 р.'
			debtCell.classList.add('back-green')
		} else {
			debtCell.classList.remove('back-green')
		}
	})
}

const colorizeRemainingAmountBySupplierDebt = (supplierDebts = []) => {
	const table = document.getElementById('transactions-table')
	if (!table || !Array.isArray(supplierDebts) || supplierDebts.length === 0)
		return

	const headers = table.querySelectorAll('thead th')
	let remainingAmountCol = -1

	headers.forEach((header, idx) => {
		if (header.dataset.name === 'remaining_amount') {
			remainingAmountCol = idx
		}
	})

	if (remainingAmountCol === -1) return

	const rows = table.querySelectorAll('tbody tr:not(.table__row--summary)')
	rows.forEach((row, idx) => {
		const cell = row.querySelectorAll('td')[remainingAmountCol]
		if (!cell) return

		const debt = supplierDebts[idx]
		if (debt === 0 || debt === '0' || debt === '0 р.' || debt === '0,00 р.') {
			cell.classList.add('back-green')
		} else {
			cell.classList.remove('back-green')
		}
	})
}

export class TablePaginator {
	constructor(config) {
		this.baseUrl = config.baseUrl || '/'
		this.entityName = config.entityName
		this.tableId = config.tableId
		this.selectors = {
			nextPage: 'next-page',
			prevPage: 'prev-page',
			firstPage: 'first-page',
			lastPage: 'last-page',
			currentPage: 'current-page',
			totalPages: 'total-pages',
			currentPageData: 'current-page-data',
			totalPagesData: 'total-pages-data',
			...config.selectors,
		}
		this.onDataLoaded = config.onDataLoaded || (() => {})
		this.buttons = {}
		this.currentPage = 1
		this.totalPages = 1
		this.initElements()
		this.initEventListeners()
	}

	initElements() {
		this.buttons.next = document.getElementById(this.selectors.nextPage)
		this.buttons.prev = document.getElementById(this.selectors.prevPage)
		this.buttons.first = document.getElementById(this.selectors.firstPage)
		this.buttons.last = document.getElementById(this.selectors.lastPage)
		this.currentPageInput = document.getElementById(this.selectors.currentPage)
		this.totalPagesSpan = document.getElementById(this.selectors.totalPages)

		try {
			const currentPageData = document.getElementById(
				this.selectors.currentPageData
			)?.textContent
			if (currentPageData) {
				this.currentPage = JSON.parse(currentPageData)
				if (this.currentPageInput) {
					this.currentPageInput.value = this.currentPage
				}
			}
		} catch (e) {
			console.error('Ошибка при получении текущей страницы:', e)
		}

		try {
			const totalPagesData = document.getElementById(
				this.selectors.totalPagesData
			)?.textContent
			if (totalPagesData) {
				this.totalPages = JSON.parse(totalPagesData)
				if (this.totalPagesSpan) {
					this.totalPagesSpan.textContent = this.totalPages
				}
				if (this.currentPageInput) {
					this.currentPageInput.max = this.totalPages
				}
			}
		} catch (e) {
			console.error('Ошибка при получении общего количества страниц:', e)
		}

		this.updateButtonStates()
	}

	initEventListeners() {
		if (this.buttons.next) {
			this.buttons.next.addEventListener('click', () => {
				this.goToPage(this.currentPage + 1)
			})
		}
		if (this.buttons.prev) {
			this.buttons.prev.addEventListener('click', () => {
				this.goToPage(this.currentPage - 1)
			})
		}
		if (this.buttons.first) {
			this.buttons.first.addEventListener('click', () => {
				this.goToPage(1)
			})
		}
		if (this.buttons.last) {
			this.buttons.last.addEventListener('click', () => {
				this.goToPage(this.totalPages)
			})
		}

		if (this.currentPageInput) {
			this.currentPageInput.addEventListener('input', () => {
				let currentPage = parseInt(this.currentPageInput.value, 10)
				if (isNaN(currentPage) || currentPage < 1) {
					this.currentPageInput.value = 1
				} else if (currentPage > this.totalPages) {
					this.currentPageInput.value = this.totalPages
				}
			})

			this.currentPageInput.addEventListener('change', () => {
				let targetPage = parseInt(this.currentPageInput.value, 10)
				if (isNaN(targetPage) || targetPage < 1) {
					targetPage = 1
				} else if (targetPage > this.totalPages) {
					targetPage = this.totalPages
				}
				this.currentPageInput.value = targetPage
				this.goToPage(targetPage)
			})
		}
	}

	updateButtonStates() {
		const isFirstPage = this.currentPage <= 1
		const isLastPage = this.currentPage >= this.totalPages

		if (this.buttons.next) this.buttons.next.disabled = isLastPage
		if (this.buttons.last) this.buttons.last.disabled = isLastPage
		if (this.buttons.prev) this.buttons.prev.disabled = isFirstPage
		if (this.buttons.first) this.buttons.first.disabled = isFirstPage

		if (this.currentPageInput) {
			this.currentPageInput.disabled = this.totalPages <= 0
		}
	}

	async goToPage(page) {
		const loader = createLoader()
		document.body.appendChild(loader)

		try {
			const response = await fetchData(
				`${this.baseUrl}${this.entityName}/list/?page=${page}`
			)
			const data = await response.json()

			if (response.ok && data.html && data.context) {
				this.updateTable(data.html)
				this.updatePagination(data.context)
				this.onDataLoaded(data)
			} else {
				this.handleError(data, response)
			}
		} catch (error) {
			console.error(`Ошибка при загрузке данных для ${this.entityName}:`, error)
			showError('Произошла ошибка при загрузке данных')
		} finally {
			loader.remove()
		}
	}

	updateTable(html) {
		const table = document.getElementById(this.tableId)
		if (!table) return

		const tbody = table.querySelector('tbody')
		if (tbody) {
			const summaryRow = tbody.querySelector('.table__row--summary')
			tbody.innerHTML = html
			if (summaryRow) {
				tbody.appendChild(summaryRow)
			}
		}
	}

	updatePagination(context) {
		const { current_page, total_pages } = context
		this.currentPage = current_page
		this.totalPages = total_pages

		if (this.currentPageInput) {
			this.currentPageInput.value = current_page
			this.currentPageInput.max = total_pages
		}
		if (this.totalPagesSpan) {
			this.totalPagesSpan.textContent = total_pages
		}

		this.updateButtonStates()
	}

	handleError(data, response) {
		const table = document.getElementById(this.tableId)
		if (table) {
			const tbody = table.querySelector('tbody')
			if (tbody) {
				tbody.innerHTML = ''
			}
		}

		if (this.currentPageInput) {
			this.currentPageInput.value = 1
			this.currentPageInput.max = 1
			this.currentPageInput.disabled = true
		}
		if (this.totalPagesSpan) {
			this.totalPagesSpan.textContent = '1'
		}

		Object.values(this.buttons).forEach(btn => {
			if (btn) btn.disabled = true
		})

		if (data.message) {
			console.log('Сообщение сервера:', data.message)
		} else if (!response.ok) {
			showError(`Ошибка загрузки данных для ${this.entityName}.`)
		}
	}
}

const baseConfig = {
	dataUrls: [],
	editFunc: () => {},
	addFunc: () => {},
	afterAddFunc: () => {},
	afterEditFunc: () => {},
	modalConfig: {},
}

const createConfig = (entity, extraConfig = {}) => {
	const config = {
		...baseConfig,
		containerId: `${entity}-container`,
		tableId: `${entity}-table`,
		formId: `${entity}-form`,
		getUrl: `${BASE_URL}${entity}/`,
		addUrl: `${BASE_URL}${entity}/add/`,
		editUrl: `${BASE_URL}${entity}/edit/`,
		deleteUrl: `${BASE_URL}${entity}/delete/`,
		...extraConfig,
	}
	return config
}

const mainConfig = createConfig(TRANSACTION, {
	dataUrls: [
		{ id: 'client', url: `${BASE_URL}clients/list/` },
		{ id: 'supplier', url: `${BASE_URL}${SUPPLIERS}/list/` },
	],
	editFunc: () => {
		setupCurrencyInput('amount')
		setupPercentInput('client_percentage')
		setupPercentInput('supplier_percentage')
		setupPercentInput('bonus_percentage')
	},
	addFunc: () => {
		setupCurrencyInput('amount')
		setupPercentInput('client_percentage')
		setupPercentInput('supplier_percentage')
		setupPercentInput('bonus_percentage')
	},
	afterAddFunc: result => {
		refreshData(`${TRANSACTION}-table`, result.id)
		const row = TableManager.getRowById(`${TRANSACTION}-table`, result.id)
		TableManager.formatCurrencyValuesForRow(`${TRANSACTION}-table`, row)

		TableManager.calculateTableSummary(`${TRANSACTION}-table`, ['profit'], {
			grouped: true,
			total: true,
		})
	},
	afterEditFunc: result => {
		refreshData(`${TRANSACTION}-table`)
		const row = TableManager.getRowById(`${TRANSACTION}-table`, result.id)
		TableManager.formatCurrencyValuesForRow(`${TRANSACTION}-table`, row)

		TableManager.calculateTableSummary(`${TRANSACTION}-table`, ['profit'], {
			grouped: true,
			total: true,
		})
	},
	afterDeleteFunc: () => {
		TableManager.calculateTableSummary(`${TRANSACTION}-table`, ['profit'], {
			grouped: true,
			total: true,
		})
	},
	modalConfig: {
		addModalUrl: '/components/main/add_transaction/',
		editModalUrl: '/components/main/add_transaction/',
		addModalTitle: 'Добавить транзакцию',
		editModalTitle: 'Редактировать транзакцию',
	},
})

const suppliersConfig = createConfig(SUPPLIERS, {
	dataUrls: [
		{ id: 'default_account', url: `${BASE_URL}accounts/list/` },
		{ id: 'branch', url: `${BASE_URL}branches/list/` },
	],
	editFunc: () => {
		setupPercentInput('cost_percentage')
	},
	addFunc: () => {
		setupPercentInput('cost_percentage')
	},
	afterAddFunc: result => refreshData(`${SUPPLIERS}-table`, result.id),
	afterEditFunc: result => refreshData(`${SUPPLIERS}-table`),
	modalConfig: {
		addModalUrl: '/components/main/add_supplier/',
		editModalUrl: '/components/main/add_supplier/',
		addModalTitle: 'Добавить поставщика',
		editModalTitle: 'Редактировать поставщика',
	},
})

const clientsConfig = createConfig(CLIENTS, {
	editFunc: () => {
		setupPercentInput('percentage')
	},
	addFunc: () => {
		setupPercentInput('percentage')
	},
	afterAddFunc: result => refreshData(`${CLIENTS}-table`, result.id),
	afterEditFunc: result => refreshData(`${CLIENTS}-table`),
	modalConfig: {
		addModalUrl: '/components/main/add_client/',
		editModalUrl: '/components/main/add_client/',
		addModalTitle: 'Добавить клиента',
		editModalTitle: 'Редактировать клиента',
	},
})

const cashflowConfig = createConfig(CASH_FLOW, {
	dataUrls: [
		{ id: 'account', url: `${BASE_URL}accounts/list/` },
		{ id: 'purpose', url: `${BASE_URL}payment_purposes/list/` },
		{ id: 'supplier', url: `${BASE_URL}${SUPPLIERS}/list/` },
	],
	editFunc: () => {
		setupCurrencyInput('amount')
		checkOperationType()
	},
	addFunc: () => {
		setupCurrencyInput('amount')
		checkOperationType()
	},
	afterAddFunc: result => {
		refreshData(`${CASH_FLOW}-table`, result.id)
		colorizeAmounts(`${CASH_FLOW}-table`)
	},
	afterEditFunc: result => {
		refreshData(`${CASH_FLOW}-table`)
		colorizeAmounts(`${CASH_FLOW}-table`)
	},
	modalConfig: {
		addModalUrl: '/components/main/add_cashflow/',
		editModalUrl: '/components/main/add_cashflow/',
		addModalTitle: 'Добавить транзакцию',
		editModalTitle: 'Редактировать транзакцию',
	},
})

const moneyTransfersConfig = createConfig(MONEY_TRANSFERS, {
	dataUrls: [
		{ id: 'source_supplier', url: `${BASE_URL}${SUPPLIERS}/list/` },
		{ id: 'source_account', url: `${BASE_URL}accounts/list/` },
		{ id: 'destination_supplier', url: `${BASE_URL}${SUPPLIERS}/list/` },
		{ id: 'destination_account', url: `${BASE_URL}accounts/list/` },
	],
	editFunc: () => {
		setupCurrencyInput('amount')
	},
	addFunc: () => {
		setupCurrencyInput('amount')
	},
	afterAddFunc: result => {
		refreshData(`${MONEY_TRANSFERS}-table`, result.id)
	},
	afterEditFunc: result => {
		refreshData(`${MONEY_TRANSFERS}-table`)
	},
	modalConfig: {
		addModalUrl: '/components/main/add_money_transfers/',
		editModalUrl: '/components/main/add_money_transfers/',
		addModalTitle: 'Добавить транзакцию',
		editModalTitle: 'Редактировать транзакцию',
	},
})

const createFormHandler = (
	submitUrl,
	tableId,
	formId,
	getUrl = [],
	dataUrls,
	modalConfig,
	onSuccess
) => {
	return new DynamicFormHandler({
		submitUrl: submitUrl,
		tableId: tableId,
		formId: formId,
		getUrl: getUrl,
		dataUrls: dataUrls,
		modalConfig: modalConfig,
		onSuccess: onSuccess,
	})
}

const paymentFormHandler = createFormHandler(
	`${BASE_URL}${TRANSACTION}/payment/`,
	mainConfig.tableId,
	`payment-form`,
	`${BASE_URL}${TRANSACTION}/`,
	[],
	{
		url: '/components/main/payment/',
		title: 'Оплата транзакции',
		...(mainConfig.modalConfig.context
			? { context: mainConfig.modalConfig.context }
			: {}),
	},
	result => {
		TableManager.updateTableRow(result, mainConfig.tableId)
		refreshData(`${TRANSACTION}-table`)
		const row = TableManager.getRowById(`${TRANSACTION}-table`, result.id)
		TableManager.formatCurrencyValuesForRow(`${TRANSACTION}-table`, row)
	}
)

const settleDebtFormHandler = createFormHandler(
	`${BASE_URL}${SUPPLIERS}/settle-debt/`,
	`debtors-table`,
	`settle-debt-form`,
	`${BASE_URL}${SUPPLIERS}/debtors/`,
	[],
	{
		url: '/components/main/settle-debt/',
		title: 'Погашение долга',
		...(mainConfig.modalConfig.context
			? { context: mainConfig.modalConfig.context }
			: {}),
	},
	result => {
		if (result.html) {
			let tableId

			switch (result.type) {
				case 'Бонусы':
					tableId = 'summary-bonus'
					break
				case 'Выдачи клиентам':
					tableId = 'summary-remaining'
					break
				case 'Поставщики':
					tableId = `branch-transactions-${result.branch}`

					TableManager.addTableRow(
						{ html: result.html_debt_repayments },
						tableId
					)

					TableManager.calculateTableSummary(
						`branch-transactions-${result.branch}`,
						['supplier_debt']
					)

					break
				default:
					tableId = `branch-transactions-${result.branch}`
			}

			TableManager.updateTableRow(result, tableId)

			refreshData(tableId)

			const row = TableManager.getRowById(result.id, tableId)
			TableManager.formatCurrencyValuesForRow(tableId, row)

			hideDebtorRowIfNoDebt(row, tableId, result.type)

			const table = document.getElementById(tableId)
			if (table) {
				const summaryCells = table.querySelectorAll('td.table__cell--summary')
				summaryCells.forEach(cell => {
					if (cell.classList.contains('text-green')) {
						cell.classList.remove('text-green')
						cell.classList.add('text-red')
					} else if (cell.classList.contains('text-red')) {
						cell.classList.remove('text-red')
						cell.classList.add('text-green')
					}
				})
				colorizeZeroDebts(tableId)
			}

			if (
				typeof result.branch === 'string' ||
				typeof result.type === 'string'
			) {
				const branchSpans = Array.from(
					document.querySelectorAll('.debtors-office-list__title')
				)
				let branchKey = null
				if (typeof result.branch === 'string') {
					branchKey = result.branch
				} else if (typeof result.type === 'string') {
					if (result.type === 'Бонусы' || result.type === 'bonus') {
						branchKey = 'Бонусы'
					} else if (
						result.type === 'Выдачи клиентам' ||
						result.type === 'remaining'
					) {
						branchKey = 'Выдачи клиентам'
					}
				}
				const branchSpan = branchSpans.find(
					span => span.textContent.trim() === branchKey.trim()
				)
				if (branchSpan) {
					const amountSpan = branchSpan.parentElement.querySelector(
						'.debtors-office-list__amount'
					)
					if (amountSpan) {
						let debt = Number(result.total_debt)
						if (!isNaN(debt)) {
							let formatted = debt.toLocaleString('ru-RU').replace(/,/g, ' ')
							formatted = formatted.replace(/,00$/, '')
							if (!formatted.endsWith('р.') && !formatted.endsWith('р')) {
								formatted = formatted + ' р.'
							}
							amountSpan.textContent = formatted
						}
					}
				}
			}
		}
	}
)

const collectionFormHandler = createFormHandler(
	`${BASE_URL}money_transfers/collection/`,
	'suppliers-account-table',
	`collection-form`,
	[],
	[
		{ id: 'source_account', url: `${BASE_URL}accounts/list/?collection=true` },
		{ id: 'source_supplier', url: `${BASE_URL}${SUPPLIERS}/list/` },
	],
	{
		url: '/components/main/collection/',
		title: 'Инкассация',
		...(mainConfig.modalConfig.context
			? { context: mainConfig.modalConfig.context }
			: {}),
	},
	result => {
		TableManager.updateTableRow(result, 'suppliers-account-table')
		const row = TableManager.getRowById(result.id, 'suppliers-account-table')
		if (row) {
			const cells = row.querySelectorAll('td')
			if (cells.length > 0) {
				cells[0].classList.add('total-column')
				if (cells.length > 1) {
					cells[cells.length - 1].classList.add('total-column')
				}
				const headerCells = document.querySelectorAll(
					'#suppliers-account-table thead th'
				)
				cells.forEach((cell, index) => {
					if (cell.textContent.trim() === 'Наличные') {
						cell.classList.add('total-column')
					}
					if (
						index < headerCells.length &&
						headerCells[index].textContent.trim() === 'Наличные'
					) {
						cell.classList.add('total-column')
					}
				})
			}
		}

		if (result.total_html) {
			const table = document.getElementById('suppliers-account-table')
			const tbody = table.querySelector('tbody')
			const lastRow = tbody.querySelector(
				'tr.total-row, tr.table__row--summary'
			)
			if (lastRow) {
				const newRow = document.createElement('tr')
				newRow.classList.add('table__row', 'total-row', 'table__row--summary')
				const parser = new DOMParser()
				const htmlDoc = parser.parseFromString(
					`<table><tr>${result.total_html}</tr></table>`,
					'text/html'
				)
				const parsedRow = htmlDoc.querySelector('tr.table__row')
				if (parsedRow) {
					newRow.innerHTML = parsedRow.innerHTML
					const cells = newRow.querySelectorAll('td')
					if (cells.length > 0) {
						cells[0].classList.add('total-column')
						if (cells.length > 1) {
							cells[cells.length - 1].classList.add('total-column')
						}
						const headerCells = table.querySelectorAll('thead th')
						cells.forEach((cell, index) => {
							if (cell.textContent.trim() === 'Наличные') {
								cell.classList.add('total-column')
							}
							if (
								index < headerCells.length &&
								headerCells[index].textContent.trim() === 'Наличные'
							) {
								cell.classList.add('total-column')
							}
						})
					}
					tbody.replaceChild(newRow, lastRow)
					TableManager.formatCurrencyValuesForRow(
						`suppliers-account-table`,
						newRow
					)
				} else {
					console.error('Не удалось распарсить HTML итоговой строки')
				}
			}
		}
	}
)

const handleTransactions = async config => {
	try {
		const transactionIdsData = document.getElementById('data-ids')?.textContent
		if (transactionIdsData) {
			const transactionIds = JSON.parse(transactionIdsData)
			setIds(transactionIds, `${TRANSACTION}-table`)
		} else {
			console.warn("Element with ID 'data-ids' not found or empty.")
		}
	} catch (e) {
		console.error('Error parsing transaction IDs data for actions column:', e)
	}
	try {
		const changedCellsData =
			document.getElementById('changed-cells')?.textContent
		if (changedCellsData) {
			const changedCells = JSON.parse(changedCellsData)
			showChangedCells(changedCells, `${TRANSACTION}-table`)
		} else {
			console.warn("Element with ID 'changed-cells' not found or empty.")
		}
	} catch (e) {
		console.error('Error parsing changed cells data:', e)
	}

	initTableHandlers(config)
	setupSelectListener()
	highlightModifiedRows()

	let supplierDebtsAll

	try {
		const supplierDebtsData =
			document.getElementById('supplier-debts')?.textContent
		if (supplierDebtsData) {
			const supplierDebts = JSON.parse(supplierDebtsData)
			supplierDebtsAll = supplierDebts
			colorizeRemainingAmountBySupplierDebt(supplierDebts)

			hideCompletedTransactions(supplierDebts)
		} else {
			console.warn("Element with ID 'supplier-debts' not found or empty.")
		}
	} catch (e) {
		console.error('Error parsing supplier-debts data:', e)
	}

	new TablePaginator({
		baseUrl: BASE_URL,
		entityName: TRANSACTION,
		tableId: `${TRANSACTION}-table`,
		onDataLoaded: data => {
			const { transaction_ids = [], changed_cells = {} } = data.context
			setIds(transaction_ids, `${TRANSACTION}-table`)
			if (Object.keys(changed_cells).length > 0) {
				showChangedCells(changed_cells, `${TRANSACTION}-table`)
			}
			highlightModifiedRows()
			TableManager.formatCurrencyValues(`${TRANSACTION}-table`)
			TableManager.calculateTableSummary(`${TRANSACTION}-table`, ['profit'], {
				grouped: true,
				total: true,
			})
		},
	})

	TableManager.calculateTableSummary(`${TRANSACTION}-table`, ['profit'], {
		grouped: true,
		total: true,
	})

	const paymentButton = document.getElementById('payment-button')
	if (paymentButton) {
		paymentButton.addEventListener('click', async function (e) {
			e.preventDefault()
			const currentRowId = TableManager.getSelectedRowId(`${TRANSACTION}-table`)
			if (currentRowId) {
				await paymentFormHandler.init(currentRowId)
				setupCurrencyInput('paid_amount')
			} else {
				console.error('ID строки не найден для действия оплаты')
			}
		})
	}

	const hideButton = document.getElementById('hide-button')
	const showAllButton = document.getElementById('show-all-button')
	const hideAllButton = document.getElementById('hide-all-button')

	if (hideButton) {
		hideButton.addEventListener('click', function () {
			const rowId = TableManager.getSelectedRowId(`${TRANSACTION}-table`)
			if (rowId) {
				toggleTransactionVisibility(rowId)
			}
		})
	}

	if (showAllButton) {
		showAllButton.addEventListener('click', function () {
			toggleAllTransactions(true, supplierDebtsAll)
		})
	}

	if (hideAllButton) {
		hideAllButton.addEventListener('click', function () {
			toggleAllTransactions(false, supplierDebtsAll)
		})
	}
}

const handleSuppliers = async config => {
	try {
		const suppliersIdsData = document.getElementById('data-ids')?.textContent
		if (suppliersIdsData) {
			const suppliersIds = JSON.parse(suppliersIdsData)
			setIds(suppliersIds, `${SUPPLIERS}-table`)
		} else {
			console.warn("Element with ID 'data-ids' not found or empty.")
		}
	} catch (e) {
		console.error('Error parsing suppliers IDs data for actions column:', e)
	}

	initTableHandlers(config)
}

const handleClients = async config => {
	try {
		const clientsIdsData = document.getElementById('data-ids')?.textContent
		if (clientsIdsData) {
			const clientsIds = JSON.parse(clientsIdsData)
			setIds(clientsIds, `${CLIENTS}-table`)
		} else {
			console.warn("Element with ID 'data-ids' not found or empty.")
		}
	} catch (e) {
		console.error('Error parsing clients IDs data for actions column:', e)
	}

	initTableHandlers(config)
}

const handleProfitDistribution = async () => {
	try {
		const profitIdsData = document.getElementById('data-ids')?.textContent
		if (profitIdsData) {
			const profitIds = JSON.parse(profitIdsData)
			setIds(profitIds, `profit_distribution-table`)
		} else {
			console.warn("Element with ID 'data-ids' not found or empty.")
		}
	} catch (e) {
		console.error('Error parsing clients IDs data for actions column:', e)
	}

	const profitDistributionButton = document.getElementById(
		'profit_distribution-button'
	)
	if (profitDistributionButton) {
		profitDistributionButton.addEventListener('click', async function (e) {
			e.preventDefault()

			const transactionId = TableManager.getSelectedRowId(
				'profit_distribution-table'
			)

			// await profitDistributionFormHandler.init(transactionId || 0) TODO:
		})
	}
}

const handleSupplierAccounts = async () => {
	const table = document.getElementById('suppliers-account-table')
	if (table) {
		const rows = table.querySelectorAll('tbody tr')
		if (rows.length > 0) {
			rows[rows.length - 1].classList.add('total-row', 'table__row--summary')
		}

		const headerCells = table.querySelectorAll('thead th')
		const lastColIndex = headerCells.length - 1
		if (lastColIndex > 0) {
			headerCells[lastColIndex].classList.add('total-column')
			headerCells[0].classList.add('total-column')
			headerCells.forEach((headerCell, index) => {
				if (headerCell.textContent.trim() === 'Наличные') {
					headerCell.classList.add('total-column')
				}
			})

			rows.forEach(row => {
				const cells = row.querySelectorAll('td')
				if (cells.length > lastColIndex) {
					cells[lastColIndex].classList.add('total-column')
				}
				if (cells.length > 0) {
					cells[0].classList.add('total-column')
				}
				cells.forEach((cell, index) => {
					if (cell.textContent.trim() === 'Наличные') {
						cell.classList.add('total-column')
					}
					if (
						index < headerCells.length &&
						headerCells[index].textContent.trim() === 'Наличные'
					) {
						cell.classList.add('total-column')
					}
				})
			})
		}
	}

	try {
		const supplierIdsData = document.getElementById('supplier-ids')?.textContent
		if (supplierIdsData) {
			const supplierIds = JSON.parse(supplierIdsData)
			setIds(supplierIds, `suppliers-account-table`)
		} else {
			console.warn("Element with ID 'supplier-ids' not found or empty.")
		}
	} catch (e) {
		console.error('Error parsing supplier IDs data for actions column:', e)
	}

	try {
		const accountIdsData = document.getElementById('account-ids')?.textContent
		if (accountIdsData) {
			const accountIds = JSON.parse(accountIdsData)
			setColumnIds(accountIds, `suppliers-account-table`)
		} else {
			console.warn("Element with ID 'account-ids' not found or empty.")
		}
	} catch (e) {
		console.error('Error parsing account IDs data for actions column:', e)
	}

	const collectionButton = document.getElementById('collection-button')
	if (collectionButton) {
		collectionButton.addEventListener('click', async function (e) {
			await collectionFormHandler.init(0)

			const supplierId = TableManager.getSelectedRowId(
				'suppliers-account-table'
			)
			const accountId = getSelectedAccountId('suppliers-account-table')
			if (supplierId && accountId && supplierId !== 'ИТОГО') {
				selectOptionById('source_supplier', supplierId)
				selectOptionById('source_account', accountId)
			}

			setupCurrencyInput('amount')
		})
	}
}

const handleCashFlow = async config => {
	try {
		const cashflowIdsData = document.getElementById('data-ids')?.textContent
		if (cashflowIdsData) {
			const cashflowIds = JSON.parse(cashflowIdsData)
			setIds(cashflowIds, `${CASH_FLOW}-table`)
		} else {
			console.warn("Element with ID 'data-ids' not found or empty.")
		}
	} catch (e) {
		console.error('Error parsing cashflow IDs data for actions column:', e)
	}

	colorizeAmounts(`${CASH_FLOW}-table`)
	initTableHandlers(config)

	new TablePaginator({
		baseUrl: BASE_URL,
		entityName: CASH_FLOW,
		tableId: `${CASH_FLOW}-table`,
		onDataLoaded: data => {
			const { cash_flow_ids = [] } = data.context
			setIds(cash_flow_ids, `${CASH_FLOW}-table`)
			colorizeAmounts(`${CASH_FLOW}-table`)
		},
	})
}

const handleReport = () => {
	const table = document.getElementById('cash_flow_report-table')
	if (table) {
		const cells = table.querySelectorAll('td:not(:first-child)')
		cells.forEach(cell => {
			const value = cell.textContent.trim()
			if (value.startsWith('-')) {
				cell.classList.add('text-red')
			} else if (value !== '0 р.' && value !== '0,00 р.') {
				cell.classList.add('text-green')
			}
		})

		const rows = table.querySelectorAll('tbody tr')
		if (rows.length > 0) {
			rows[rows.length - 1].classList.add('total-row')
		}
	}
}

const handleMoneyTransfers = async config => {
	try {
		const dataIdsData = document.getElementById('data-ids')?.textContent
		if (dataIdsData) {
			const dataIds = JSON.parse(dataIdsData)
			setIds(dataIds, `${MONEY_TRANSFERS}-table`)
		} else {
			console.warn("Element with ID 'data-ids' not found or empty.")
		}
	} catch (e) {
		console.error(
			'Error parsing money transfers IDs data for actions column:',
			e
		)
	}

	initTableHandlers(config)
}

const handleDebtors = () => {
	document.querySelectorAll('.debtors-office-list__amount').forEach(el => {
		let text = el.textContent.trim()
		text = text.replace(/,00$/, '')
		let num = text.replace(/\s/g, '').replace('р.', '').replace('р', '')
		let number = Number(num.replace(',', '.'))
		if (!isNaN(number)) {
			let formatted = number.toLocaleString('ru-RU').replace(/,/g, ' ')
			text = formatted
		}
		if (!text.endsWith('р.') && !text.endsWith('р')) {
			text = text + ' р.'
		}
		el.textContent = text

		if (el.classList.contains('text-green')) {
			el.classList.remove('text-green')
			el.classList.add('text-red')
		} else if (el.classList.contains('text-red')) {
			el.classList.remove('text-red')
			el.classList.add('text-green')
		}
	})

	document
		.querySelectorAll('.debtors-office-list__row')
		.forEach(function (row) {
			row.addEventListener('click', async function (e) {
				var btn = row.querySelector('.debtors-office-list__toggle')
				var targetId = row.getAttribute('data-target')
				var details = document.getElementById(targetId)
				if (!details) return
				var isOpen = details.classList.toggle('open')
				btn.classList.toggle('open', isOpen)

				if (isOpen && !details.dataset.loaded) {
					let type = targetId.startsWith('branch-') ? 'branch' : 'summary'
					let value = row
						.querySelector('.debtors-office-list__title')
						.textContent.trim()

					const loader = createLoader()
					document.body.appendChild(loader)
					try {
						const response = await fetch(
							`/suppliers/debtors/details/?type=${type}&value=${encodeURIComponent(
								value
							)}`
						)

						if (!response.ok) {
							const errorText = await response.json()
							throw new Error(`${errorText.message}`)
						}

						const data = await response.json()

						if (type === 'branch') {
							details.innerHTML =
								'<div class="debtors-details-title">Сделки</div>' +
								data.html_transactions +
								'<div class="debtors-details-title">Выдано</div>' +
								data.html_repayments
							;[data.transactions_table_id, data.repayments_table_id].forEach(
								tableId => {
									const table = details.querySelector(`#${tableId}`)
									if (table) {
										const tbody = table.querySelector('.table__body')
										if (tbody && !tbody.children.length) {
											const emptyRow = document.createElement('tr')
											emptyRow.className = 'table__row table__row--empty'
											const td = document.createElement('td')
											td.colSpan =
												table.querySelectorAll('thead th').length || 1
											td.className = 'table__cell table__cell--empty'
											td.textContent = 'Нет данных'
											emptyRow.appendChild(td)
											tbody.appendChild(emptyRow)
										} else {
											setIds(data.data_ids, data.transactions_table_id)

											TableManager.calculateTableSummary(
												data.transactions_table_id,
												['supplier_debt']
											)
										}
									}
								}
							)
						} else {
							details.innerHTML = data.html

							const table = details.querySelector(`#${data.table_id}`)
							if (table) {
								const tbody = table.querySelector('.table__body')
								if (tbody && !tbody.children.length) {
									const emptyRow = document.createElement('tr')
									emptyRow.className = 'table__row table__row--empty'
									const td = document.createElement('td')
									td.colSpan = table.querySelectorAll('thead th').length || 1
									td.className = 'table__cell table__cell--empty'
									td.textContent = 'Нет данных'
									emptyRow.appendChild(td)
									tbody.appendChild(emptyRow)
								} else {
									setIds(data.data_ids, data.table_id)
								}
							}
						}
						details.dataset.loaded = '1'
						TableManager.init()

						const table = details.querySelector('table')

						const summaryCells = table.querySelectorAll(
							'td.table__cell--summary'
						)
						summaryCells.forEach(cell => {
							if (cell.classList.contains('text-green')) {
								cell.classList.remove('text-green')
								cell.classList.add('text-red')
							} else if (cell.classList.contains('text-red')) {
								cell.classList.remove('text-red')
								cell.classList.add('text-green')
							}
						})

						colorizeZeroDebts(table.id)
						hideCompletedDebtors(table.id, type === 'branch' ? 'branch' : value)

						TableManager.setInitialCellSelection()
					} catch (err) {
						details.textContent = ''
					} finally {
						loader.remove()
					}
				}
			})
		})

	const officeList = document.querySelector('.debtors-office-list')
	if (officeList) {
		const rows = officeList.querySelectorAll('.debtors-office-list__row')
		if (rows.length === 1) {
			rows[0].click()
		}
	}
	const settleDebtButton = document.getElementById('settle-debt-button')
	if (settleDebtButton) {
		settleDebtButton.addEventListener('click', async function (e) {
			e.preventDefault()

			const selectedRow = document.querySelector('td.table__cell--selected')
			const table = selectedRow ? selectedRow.closest('table') : null

			if (table) {
				const currentRowId = TableManager.getSelectedRowId(table.id)
				if (currentRowId) {
					await settleDebtFormHandler.init(currentRowId)
					setupCurrencyInput('amount')
					const typeInput = document.getElementById('type')
					if (typeInput) {
						if (table.id === 'summary-bonus') {
							typeInput.value = 'bonus'
						} else if (table.id === 'summary-remaining') {
							typeInput.value = 'remaining'
						} else if (table.id.startsWith('branch-transactions')) {
							typeInput.value = 'branch'
						}
					}
				} else {
					console.error('ID строки не найден для действия оплаты долга')
				}
			}
		})
	}

	const hideButton = document.getElementById('hide-button')
	const showAllButton = document.getElementById('show-all-button')
	const hideAllButton = document.getElementById('hide-all-button')
	if (hideButton) {
		hideButton.addEventListener('click', function () {
			const selectedRow = document.querySelector('td.table__cell--selected')
			const table = selectedRow ? selectedRow.closest('table') : null

			if (table) {
				const rowId = TableManager.getSelectedRowId(table.id)

				if (rowId) {
					toggleDebtorVisibility(rowId, table.id)
				}
			}
		})
	}
	if (showAllButton) {
		showAllButton.addEventListener('click', function () {
			const selectedRow = document.querySelector('td.table__cell--selected')
			const table = selectedRow ? selectedRow.closest('table') : null

			if (table) {
				toggleAllDebtors(true, table.id)
			}
		})
	}
	if (hideAllButton) {
		hideAllButton.addEventListener('click', function () {
			const selectedRow = document.querySelector('td.table__cell--selected')
			const table = selectedRow ? selectedRow.closest('table') : null

			if (table) {
				toggleAllDebtors(false, table.id)
			}
		})
	}
}

document.addEventListener('DOMContentLoaded', function () {
	TableManager.init()
	addMenuHandler()

	const pathname = window.location.pathname
	const regex = /^(?:\/[\w-]+)?\/([\w-]+)\/?$/
	const match = pathname.match(regex)
	const urlName = match ? match[1].replace(/-/g, '_') : null

	if (urlName) {
		switch (urlName) {
			case 'accounts':
				TableManager.calculateTableSummary('accounts-table', ['balance'], {
					grouped: true,
					total: true,
				})
				break
			case `${SUPPLIERS}`:
				handleSuppliers(suppliersConfig)
				break
			case `${CLIENTS}`:
				handleClients(clientsConfig)
				break
			case `supplier_accounts`:
				handleSupplierAccounts()
				break
			case `${CASH_FLOW}`:
				handleCashFlow(cashflowConfig)
				break
			case `report`:
				handleReport()
				break
			case `${MONEY_TRANSFERS}`:
				handleMoneyTransfers(moneyTransfersConfig)
				break
			case `${TRANSACTION}`:
				handleTransactions(mainConfig)
				break
			case `debtors`:
				handleDebtors()
				break
			case `profit_distribution`:
				handleProfitDistribution()
				break
			default:
				console.warn(`Unknown URL name: ${urlName}`)
				break
		}
	} else if (urlName === null && pathname === '/') {
		handleTransactions(mainConfig)
	}
})
