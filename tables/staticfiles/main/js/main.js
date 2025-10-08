import { DynamicFormHandler } from '/static/js/dynamicFormHandler.js'
import SelectHandler from '/static/js/selectHandler.js'
import { TableManager } from '/static/js/table.js'
import { initTableHandlers } from '/static/js/tableHandlers.js'
import {
	createLoader,
	getCSRFToken,
	showError,
	showQuestion,
} from '/static/js/ui-utils.js'

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

const formatAmountString = value => {
	let num = Number(
		String(value)
			.replace(/\s/g, '')
			.replace('р.', '')
			.replace('р', '')
			.replace(',', '.')
	)
	if (isNaN(num)) return value
	let formatted = num.toLocaleString('ru-RU', {
		minimumFractionDigits: 0,
		maximumFractionDigits: 2,
	})
	formatted = formatted.replace(/,00$/, '')
	if (!formatted.endsWith('р.') && !formatted.endsWith('р')) {
		formatted += ' р.'
	}
	return formatted
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

async function saveHiddenRowsState(tableId) {
	const rows = document.querySelectorAll(`#${tableId} tbody tr[data-id]`)
	const hiddenIds = []
	rows.forEach(row => {
		if (row.classList.contains('hidden-row')) {
			hiddenIds.push(row.getAttribute('data-id'))
		}
	})
	try {
		await fetch('/hidden_rows/set/', {
			method: 'POST',
			headers: {
				'X-CSRFToken': getCSRFToken(),
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({ table: tableId, hidden_ids: hiddenIds }),
		})
	} catch (e) {
		console.error('Ошибка сохранения скрытых строк:', e)
	}
}

async function saveShowAllState(tableId) {
	try {
		await fetch('/hidden_rows/set/', {
			method: 'POST',
			headers: {
				'X-CSRFToken': getCSRFToken(),
				'Content-Type': 'application/json',
			},
			body: JSON.stringify({ table: tableId, hidden_ids: [] }),
		})
	} catch (e) {
		console.error('Ошибка сохранения состояния "Показать все":', e)
	}
}

async function restoreHiddenRowsState(tableId) {
	try {
		const response = await fetch(`/hidden_rows/get/?table=${tableId}`)
		if (!response.ok) return
		const { hidden_ids = [] } = await response.json()
		const rows = document.querySelectorAll(`#${tableId} tbody tr[data-id]`)
		rows.forEach(row => {
			const id = row.getAttribute('data-id')
			if (hidden_ids.includes(id)) {
				row.classList.add('hidden-row')
			} else {
				row.classList.remove('hidden-row')
			}
		})
		updateHiddenRowsCounter()
	} catch (e) {
		console.error('Ошибка загрузки скрытых строк:', e)
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

const hideCompletedTransactions = debts => {
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
	let manualHiddenIds = []
	try {
		manualHiddenIds = JSON.parse(
			localStorage.getItem(`${TRANSACTION}-table-hidden-rows`) || '[]'
		)
	} catch (e) {}

	let hiddenIds = new Set(manualHiddenIds)

	rows.forEach((row, idx) => {
		const debtCell = row.querySelectorAll('td')[debtColumnIndex]
		const docsCell = row.querySelectorAll('td')[docsColumnIndex]

		if (!debtCell || !docsCell) return

		const debtValue = debtCell.textContent.trim()
		const docsChecked =
			docsCell.querySelector('input[type="checkbox"]')?.checked ||
			docsCell.querySelector('.checkbox--checked') !== null

		const bonusDebt =
			debts.bonus_debt && debts.bonus_debt[idx] !== undefined
				? debts.bonus_debt[idx]
				: null
		const clientDebt =
			debts.client_debt && debts.client_debt[idx] !== undefined
				? debts.client_debt[idx]
				: null
		const investorDebt =
			debts.investor_debt && debts.investor_debt[idx] !== undefined
				? debts.investor_debt[idx]
				: null

		const isBonusDebtZero =
			bonusDebt === 0 ||
			bonusDebt === '0' ||
			bonusDebt === '0 р.' ||
			bonusDebt === '0,00 р.' ||
			bonusDebt === '0.00' ||
			bonusDebt === null

		const isClientDebtZero =
			clientDebt === 0 ||
			clientDebt === '0' ||
			clientDebt === '0 р.' ||
			clientDebt === '0,00 р.' ||
			clientDebt === '0.00' ||
			clientDebt === null

		const isInvestorDebtZero =
			investorDebt === 0 ||
			investorDebt === '0' ||
			investorDebt === '0 р.' ||
			investorDebt === '0,00 р.' ||
			investorDebt === '0.00' ||
			investorDebt === null

		if (
			(debtValue === '0 р.' || debtValue === '0,00 р.') &&
			docsChecked &&
			isBonusDebtZero &&
			isClientDebtZero &&
			isInvestorDebtZero
		) {
			row.classList.add('hidden-row', 'row-done')
			const rowId = row.getAttribute('data-id')
			if (rowId) hiddenIds.add(rowId)
		}
	})

	localStorage.setItem(
		`${TRANSACTION}-table-hidden-rows`,
		JSON.stringify(Array.from(hiddenIds))
	)
	localStorage.setItem(`${TRANSACTION}-table-show-all`, 'false')

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

const toggleAllTransactions = (show, debts) => {
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

			const bonusDebt =
				debts.bonus_debt && debts.bonus_debt[idx] !== undefined
					? debts.bonus_debt[idx]
					: null
			const clientDebt =
				debts.client_debt && debts.client_debt[idx] !== undefined
					? debts.client_debt[idx]
					: null
			const investorDebt =
				debts.investor_debt && debts.investor_debt[idx] !== undefined
					? debts.investor_debt[idx]
					: null

			const isBonusDebtZero =
				bonusDebt === 0 ||
				bonusDebt === '0' ||
				bonusDebt === '0 р.' ||
				bonusDebt === '0,00 р.' ||
				bonusDebt === '0.00' ||
				bonusDebt === null

			const isClientDebtZero =
				clientDebt === 0 ||
				clientDebt === '0' ||
				clientDebt === '0 р.' ||
				clientDebt === '0,00 р.' ||
				clientDebt === '0.00' ||
				clientDebt === null

			const isInvestorDebtZero =
				investorDebt === 0 ||
				investorDebt === '0' ||
				investorDebt === '0 р.' ||
				investorDebt === '0,00 р.' ||
				investorDebt === '0.00' ||
				investorDebt === null

			if (
				(debtValue === '0 р.' || debtValue === '0,00 р.') &&
				docsChecked &&
				isBonusDebtZero &&
				isClientDebtZero &&
				isInvestorDebtZero
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
	const hideAllButton = document.getElementById('hide-all-button')
	const showAllButton = document.getElementById('show-all-button')
	const settleDebtButton = document.getElementById('settle-debt-button')
	const settleDebtAllButton = document.getElementById('settle-debt-all-button')
	const repaymentsEditButton = document.getElementById('repayment-edit-button')
	const detailButton = document.getElementById('detail-button')

	const withdrawalButton = document.getElementById('withdrawal-button')
	const contributionButton = document.getElementById('contribution-button')

	function showMenu(pageX, pageY) {
		menu.style.display = 'block'

		const clientX = pageX - window.scrollX
		const clientY = pageY - window.scrollY

		const viewportWidth =
			window.innerWidth || document.documentElement.clientWidth
		const viewportHeight =
			window.innerHeight || document.documentElement.clientHeight

		const rect = menu.getBoundingClientRect()
		const menuWidth = rect.width || 200
		const menuHeight = rect.height || 200

		const margin = 8
		const offset = 10

		let left = clientX + offset
		if (left + menuWidth > viewportWidth - margin) {
			left = Math.max(margin, viewportWidth - menuWidth - margin)
		}
		if (left < margin) left = margin

		const bottomThreshold = viewportHeight * 0.75
		let top
		if (clientY > bottomThreshold) {
			top = clientY - menuHeight - offset
			if (top < margin) top = margin
		} else {
			top = clientY + offset
			if (top + menuHeight > viewportHeight - margin) {
				top = Math.max(margin, viewportHeight - menuHeight - margin)
			}
		}

		menu.style.left = `${left}px`
		menu.style.top = `${top}px`
	}

	if (menu) {
		document.addEventListener('contextmenu', function (e) {
			const multiSelected =
				document.querySelectorAll('.table__cell--selected').length > 1
			if (multiSelected) {
				e.preventDefault()
				if (addButton) addButton.style.display = 'none'
				if (editButton) editButton.style.display = 'none'
				if (deleteButton) deleteButton.style.display = 'none'
				if (paymentButton) paymentButton.style.display = 'none'
				if (hideButton) hideButton.style.display = 'none'
				if (settleDebtButton) settleDebtButton.style.display = 'none'
				if (settleDebtAllButton) settleDebtAllButton.style.display = 'none'
				if (repaymentsEditButton) repaymentsEditButton.style.display = 'none'
				if (detailButton) detailButton.style.display = 'none'
				if (withdrawalButton) withdrawalButton.style.display = 'none'
				if (contributionButton) contributionButton.style.display = 'none'
				if (showAllButton) showAllButton.style.display = 'none'

				if (hideAllButton) hideAllButton.style.display = 'block'

				showMenu(e.pageX, e.pageY)
				return
			}

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
				if (showAllButton) showAllButton.style.display = 'block'
				if (settleDebtButton) {
					if (
						(table.id && table.id.startsWith('branch-repayments-')) ||
						table.id === 'investor-operations-table'
					) {
						settleDebtButton.style.display = 'none'
					} else if (table.id === 'investors-table') {
						settleDebtButton.style.display = 'none'
						settleDebtButton.dataset.type = ''
					} else {
						settleDebtButton.style.display = 'block'
						settleDebtButton.textContent = 'Погасить долг'
						settleDebtButton.dataset.type = ''
					}
				}
				if (settleDebtAllButton) {
					if (table.id === 'summary-profit') {
						settleDebtAllButton.style.display = 'block'
					} else {
						settleDebtAllButton.style.display = 'none'
					}
				}
				if (repaymentsEditButton) {
					if (table.id && table.id.startsWith('branch-repayments-')) {
						repaymentsEditButton.style.display = 'block'
					} else {
						repaymentsEditButton.style.display = 'none'
					}
				}

				if (table.id === 'cash_flow-table') {
					const headers = table.querySelectorAll('thead th')
					let purposeIndex = -1
					headers.forEach((th, idx) => {
						if (th.dataset.name === 'purpose') purposeIndex = idx
					})
					if (purposeIndex !== -1) {
						const cells = row.querySelectorAll('td')
						const purposeCell = cells[purposeIndex]
						if (
							purposeCell &&
							(purposeCell.textContent.trim() === 'Перевод' ||
								purposeCell.textContent.trim() === 'Инкассация' ||
								purposeCell.textContent.trim() === 'Погашение долга поставщика')
						) {
							e.preventDefault()

							if (editButton) editButton.style.display = 'none'
							if (deleteButton) deleteButton.style.display = 'none'
						}
					}
				}

				if (table.id === 'cash_flow_report-table') {
					if (detailButton) detailButton.style.display = 'block'
				}

				if (table.id === 'investors-table') {
					const selectedCell = document.querySelector(
						'td.table__cell--selected'
					)
					if (selectedCell) {
						const cellIndex = Array.from(
							selectedCell.parentNode.children
						).indexOf(selectedCell)
						const th = table.querySelectorAll('thead th')[cellIndex]
						const colName = th ? th.dataset.name : null

						if (colName === 'balance') {
							withdrawalButton.style.display = 'block'
							contributionButton.style.display = 'block'
						}
					}
				} else {
					if (withdrawalButton) withdrawalButton.style.display = 'none'
					if (contributionButton) contributionButton.style.display = 'none'
				}

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
				if (settleDebtAllButton) settleDebtAllButton.style.display = 'none'
				if (repaymentsEditButton) repaymentsEditButton.style.display = 'none'
				if (detailButton) detailButton.style.display = 'none'
				if (withdrawalButton) withdrawalButton.style.display = 'none'
				if (contributionButton) contributionButton.style.display = 'none'
				if (showAllButton) showAllButton.style.display = 'block'

				const pathname = window.location.pathname
				const regex = /^(?:\/[\w-]+)?\/([\w-]+)\/?$/
				const match = pathname.match(regex)
				const urlName = match ? match[1].replace(/-/g, '_') : null

				if (urlName === 'balance') {
					if (showAllButton) showAllButton.style.display = 'none'
					if (hideAllButton) hideAllButton.style.display = 'none'
					if (hideButton) hideButton.style.display = 'none'
					if (addButton) addButton.style.display = 'none'
				}

				showMenu(e.pageX, e.pageY)
			}

			const item = e.target.closest('.debtors-office-list__row-item')
			if (item) {
				const h4 = item.querySelector('h4')
				const settleDebtButton = document.getElementById('settle-debt-button')
				if (
					h4 &&
					['Оборудование', 'Кредит', 'Краткосрочные обязательства'].includes(
						h4.textContent.trim()
					)
				) {
					if (settleDebtButton) {
						settleDebtButton.style.display = 'block'
						settleDebtButton.textContent = 'Изменить сумму'
						settleDebtButton.dataset.type = h4.textContent.trim()
					}
				}
			}
		})

		let touchTimer = null
		let touchStartTarget = null
		let touchStartX = 0
		let touchStartY = 0
		const LONG_PRESS_DELAY = 600

		document.addEventListener(
			'touchstart',
			function (ev) {
				if (ev.touches && ev.touches.length > 1) return
				const t = ev.touches ? ev.touches[0] : null
				if (!t) return
				touchStartX = t.pageX
				touchStartY = t.pageY
				touchStartTarget = ev.target

				touchTimer = setTimeout(() => {
					const evt = new MouseEvent('contextmenu', {
						bubbles: true,
						cancelable: true,
						view: window,
						clientX: touchStartX,
						clientY: touchStartY,
						pageX: touchStartX,
						pageY: touchStartY,
					})
					try {
						touchStartTarget.dispatchEvent(evt)
					} catch (e) {
						document.dispatchEvent(evt)
					}
					touchTimer = null
				}, LONG_PRESS_DELAY)
			},
			{ passive: true }
		)

		document.addEventListener(
			'touchmove',
			function () {
				if (touchTimer) {
					clearTimeout(touchTimer)
					touchTimer = null
				}
			},
			{ passive: true }
		)

		document.addEventListener(
			'touchend',
			function () {
				if (touchTimer) {
					clearTimeout(touchTimer)
					touchTimer = null
				}
			},
			{ passive: true }
		)

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
	} catch (error) {
		console.error('Ошибка при отметке транзакции:', error)
		showError('Ошибка при отметке транзакции как прочитанной')
	}
}

function hideCompletedExchangeRows(fromCompleted = [], toCompleted = []) {
	const fromRows = document.querySelectorAll(
		'#from_us_exchange-table tbody tr:not(.table__row--summary)'
	)
	const toRows = document.querySelectorAll(
		'#to_us_exchange-table tbody tr:not(.table__row--summary)'
	)

	const fromCompletedIds = (
		Array.isArray(fromCompleted) ? fromCompleted : []
	).map(String)
	const toCompletedIds = (Array.isArray(toCompleted) ? toCompleted : []).map(
		String
	)

	fromRows.forEach(row => {
		const rowId = row.getAttribute('data-id')
		if (fromCompletedIds.includes(rowId)) {
			row.classList.add('hidden-row')
			row.classList.add('row-done')
		} else {
			row.classList.remove('hidden-row')
			row.classList.remove('row-done')
		}
	})

	toRows.forEach(row => {
		const rowId = row.getAttribute('data-id')
		if (toCompletedIds.includes(rowId)) {
			row.classList.add('hidden-row')
			row.classList.add('row-done')
		} else {
			row.classList.remove('hidden-row')
			row.classList.remove('row-done')
		}
	})
}

function toggleExchangeRowVisibility(rowId, tableId) {
	const row = document.querySelector(`#${tableId} tr[data-id="${rowId}"]`)
	if (!row) return
	row.classList.toggle('hidden-row')
}

function toggleAllExchangeRows(show, tableId, completedIds = []) {
	const rows = document.querySelectorAll(
		`#${tableId} tbody tr:not(.table__row--summary)`
	)
	const completedStrIds = (Array.isArray(completedIds) ? completedIds : []).map(
		String
	)
	if (show) {
		rows.forEach(row => row.classList.remove('hidden-row'))
	} else {
		rows.forEach(row => {
			const rowId = row.getAttribute('data-id')
			if (completedStrIds.includes(rowId)) {
				row.classList.add('hidden-row')
			}
		})
	}
}

const createExchangeFormHandler = action => {
	const urlMap = {
		add: `${BASE_URL}money_transfers/add/?exchange=true`,
		edit: `${BASE_URL}money_transfers/edit/`,
		delete: `${BASE_URL}money_transfers/delete/`,
	}
	return createFormHandler(
		urlMap[action],
		'',
		`money_transfers-form`,
		`${BASE_URL}money_transfers/`,
		[
			{ id: 'source_supplier', url: `${BASE_URL}${SUPPLIERS}/list/` },
			{ id: 'destination_supplier', url: `${BASE_URL}${SUPPLIERS}/list/` },
		],
		{
			url: '/components/main/add_money_transfers/',
			title:
				action === 'add'
					? 'Добавить обмен'
					: action === 'edit'
					? 'Редактировать обмен'
					: 'Удалить обмен',
			...(mainConfig.modalConfig.context
				? { context: mainConfig.modalConfig.context }
				: {}),
		},
		result => {
			const tableId =
				result.transfer_type === 'from_us'
					? 'from_us_exchange-table'
					: 'to_us_exchange-table'

			if (result.type === 'create') {
				TableManager.addTableRow(
					result,
					result.transfer_type === 'from_us'
						? 'from_us_exchange-table'
						: 'to_us_exchange-table'
				)

				const table = document.getElementById(tableId)
				if (table) {
					const rows = table.querySelectorAll(
						'tbody tr:not(.table__row--summary)'
					)
					if (rows.length > 0) {
						const lastRow = rows[rows.length - 1]
						lastRow.setAttribute('data-id', result.id)
					}
				}
			} else if (result.type === 'edit') {
				if (
					result.old_transfer_type &&
					result.old_transfer_type !== result.transfer_type
				) {
					const row = document.querySelector(
						`#${
							result.old_transfer_type === 'from_us'
								? 'from_us_exchange-table'
								: 'to_us_exchange-table'
						} tr[data-id="${result.id}"]`
					)
					if (row) row.remove()

					TableManager.addTableRow(
						result,
						result.transfer_type === 'from_us'
							? 'from_us_exchange-table'
							: 'to_us_exchange-table'
					)

					const table = document.getElementById(tableId)
					if (table) {
						const rows = table.querySelectorAll(
							'tbody tr:not(.table__row--summary)'
						)
						if (rows.length > 0) {
							const lastRow = rows[rows.length - 1]
							lastRow.setAttribute('data-id', result.id)
						}
					}
				} else {
					TableManager.updateTableRow(
						result,
						result.transfer_type === 'from_us'
							? 'from_us_exchange-table'
							: 'to_us_exchange-table'
					)
				}
			}

			let to_us_completed = result.to_us_completed || []
			let from_us_completed = result.from_us_completed || []

			const counted_from_us =
				Array.isArray(result?.counted_from_us) &&
				result.counted_from_us.length > 0
					? result.counted_from_us
					: [0]

			const counted_to_us =
				Array.isArray(result?.counted_to_us) && result.counted_to_us.length > 0
					? result.counted_to_us
					: [0]

			const filteredFrom = counted_from_us.filter(
				id => !from_us_completed.includes(id)
			)

			const filteredTo = counted_to_us.filter(
				id => !to_us_completed.includes(id)
			)

			TableManager.calculateTableSummary('from_us_exchange-table', ['amount'], {
				ids: filteredFrom && filteredFrom.length > 0 ? filteredFrom : [0],
			})
			TableManager.calculateTableSummary('to_us_exchange-table', ['amount'], {
				ids: filteredTo,
			})
			highlightExchangeTotals(counted_from_us)
		}
	)
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

		if (response) {
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
			showError(
				response.message || 'Ошибка при отметке транзакций как прочитанных'
			)
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
					const bonusPercentageInput =
						document.getElementById('bonus_percentage')
					if (percentageInput && data.percentage !== undefined) {
						percentageInput.value = data.percentage
						setupPercentInput('client_percentage')
					}

					if (bonusPercentageInput && data.bonus_percentage !== undefined) {
						bonusPercentageInput.value = data.bonus_percentage
						setupPercentInput('bonus_percentage')
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

function highlightExchangeTotals(counted_from_us = []) {
	const fromTable = document.getElementById('from_us_exchange-table')
	const toTable = document.getElementById('to_us_exchange-table')

	let fromUsValue = 0
	let toUsValue = 0

	if (fromTable) {
		const summaryRow = fromTable.querySelector('tr.table__row--summary')
		const amountTh = fromTable.querySelector('th[data-name="amount"]')
		if (summaryRow && amountTh) {
			const amountIndex = Array.from(amountTh.parentNode.children).indexOf(
				amountTh
			)
			const amountCell = summaryRow.querySelectorAll('td')[amountIndex]
			if (amountCell) {
				const text = amountCell.textContent.trim()
				fromUsValue = Number(
					text
						.replace(/\s/g, '')
						.replace('р.', '')
						.replace('р', '')
						.replace(',', '.')
				)
			}
		}
	}

	if (toTable) {
		const summaryRow = toTable.querySelector('tr.table__row--summary')
		const amountTh = toTable.querySelector('th[data-name="amount"]')
		if (summaryRow && amountTh) {
			const amountIndex = Array.from(amountTh.parentNode.children).indexOf(
				amountTh
			)
			const amountCell = summaryRow.querySelectorAll('td')[amountIndex]
			if (amountCell) {
				const text = amountCell.textContent.trim()
				toUsValue = Number(
					text
						.replace(/\s/g, '')
						.replace('р.', '')
						.replace('р', '')
						.replace(',', '.')
				)
			}
		}
	}

	const totalsBlock = document.querySelector('.exchange-totals')
	if (!totalsBlock) return

	const fromUsSpan = totalsBlock.querySelector('span')
	const toUsSpan = totalsBlock.querySelectorAll('span')[1]
	const okButton = document.getElementById('exchange-summary-button')

	if (!fromUsSpan || !toUsSpan || !okButton) return

	fromUsSpan.textContent = `${fromUsValue.toLocaleString('ru-RU')} р.`
	toUsSpan.textContent = `${toUsValue.toLocaleString('ru-RU')} р.`

	fromUsSpan.classList.remove('text-green', 'text-red', 'text-bold')
	toUsSpan.classList.remove('text-green', 'text-red', 'text-bold')

	if (toUsValue < fromUsValue) {
		toUsSpan.classList.add('text-red', 'text-bold')
		okButton.disabled = true
	} else if (toUsValue === 0 && fromUsValue === 0) {
		okButton.disabled = true
	} else if (toUsValue === fromUsValue) {
		fromUsSpan.classList.add('text-green', 'text-bold')
		toUsSpan.classList.add('text-green', 'text-bold')
		okButton.disabled = false
	} else if (toUsValue > fromUsValue) {
		toUsSpan.classList.add('text-green', 'text-bold')
		okButton.disabled = false
	}

	const fromRows = document.querySelectorAll('#from_us_exchange-table tbody tr')
	const countedIds = (
		Array.isArray(counted_from_us) ? counted_from_us : []
	).map(String)
	fromRows.forEach(row => {
		if (row.classList.contains('table__row--summary')) return
		if (!countedIds.includes(row.getAttribute('data-id'))) {
			row.classList.add('row-done--color')
		} else {
			row.classList.remove('row-done--color')
		}
	})
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
		if (
			debtValue === '0' ||
			debtValue === '0 р.' ||
			debtValue === '0,00 р.' ||
			debtValue === '0.00'
		) {
			row.classList.add('row-done')

			debtCell.textContent = '0 р.'
			debtCell.classList.add('back-green')
		} else {
			debtCell.classList.remove('back-green')
		}
	})
}

const colorizeRemainingAmountByDebts = (debts = {}) => {
	const table = document.getElementById('transactions-table')

	if (!table || typeof debts !== 'object') return

	const headers = table.querySelectorAll('thead th')
	let remainingAmountCol = -1
	let bonusCol = -1
	let clientPercentageCol = -1
	let profitCol = -1

	headers.forEach((header, idx) => {
		if (header.dataset.name === 'bonus') {
			bonusCol = idx
		}
		if (header.dataset.name === 'remaining_amount') {
			clientPercentageCol = idx
		}

		if (header.dataset.name === 'profit') {
			profitCol = idx
		}
	})
	const rows = table.querySelectorAll('tbody tr:not(.table__row--summary)')
	rows.forEach((row, idx) => {
		if (remainingAmountCol !== -1 && debts) {
			const cell = row.querySelectorAll('td')[remainingAmountCol]
			const debt = debts.supplier_debts[idx]

			if (cell) {
				if (
					debt === 0 ||
					debt === '0' ||
					debt === '0 р.' ||
					debt === '0,00 р.' ||
					debt === '0.00'
				) {
					cell.classList.add('back-green')
				} else {
					cell.classList.remove('back-green')
				}
			}
		}
		if (bonusCol !== -1 && debts.bonus_debt) {
			const cell = row.querySelectorAll('td')[bonusCol]
			const debt = debts.bonus_debt[idx]

			if (cell) {
				if (
					(debt === 0 ||
						debt === '0' ||
						debt === '0 р.' ||
						debt === '0,00 р.' ||
						debt === '0.00') &&
					cell.textContent.trim() !== '0'
				) {
					cell.classList.add('back-green')
				} else {
					cell.classList.remove('back-green')
				}
			}
		}
		if (clientPercentageCol !== -1 && debts.client_debt) {
			const cell = row.querySelectorAll('td')[clientPercentageCol]
			const debt = debts.client_debt[idx]

			if (cell) {
				if (
					debt === 0 ||
					debt === '0' ||
					debt === '0 р.' ||
					debt === '0,00 р.' ||
					debt === '0.00'
				) {
					cell.classList.add('back-green')
				} else {
					cell.classList.remove('back-green')
				}
			}
		}
		if (profitCol !== -1 && debts.investor_debt) {
			const cell = row.querySelectorAll('td')[profitCol]
			const debt = debts.investor_debt[idx]

			if (cell) {
				if (
					debt === 0 ||
					debt === '0' ||
					debt === '0 р.' ||
					debt === '0,00 р.' ||
					debt === '0.00'
				) {
					cell.classList.add('back-green')
				} else {
					cell.classList.remove('back-green')
				}
			}
		}
	})
}

function colorizeRemainingAmountByDebtsRow(row, debts = {}) {
	if (!row || typeof debts !== 'object') return

	const table = row.closest('table')
	if (!table) return

	const headers = table.querySelectorAll('thead th')
	let remainingAmountCol = -1
	let bonusCol = -1
	let clientPercentageCol = -1
	let profitCol = -1

	headers.forEach((header, idx) => {
		if (header.dataset.name === 'supplier_percentage') {
		}
		if (header.dataset.name === 'bonus') {
			bonusCol = idx
		}
		if (header.dataset.name === 'remaining_amount') {
			clientPercentageCol = idx
		}
		if (header.dataset.name === 'profit') {
			profitCol = idx
		}
	})

	const cells = row.querySelectorAll('td')
	if (bonusCol !== -1 && debts.bonus_debt !== undefined) {
		const cell = cells[bonusCol]
		const debt = debts.bonus_debt
		if (cell) {
			if (
				debt === 0 ||
				debt === '0' ||
				debt === '0 р.' ||
				debt === '0,00 р.' ||
				debt === '0.00'
			) {
				cell.classList.add('back-green')
			} else {
				cell.classList.remove('back-green')
			}
		}
	}
	if (clientPercentageCol !== -1 && debts.client_debt !== undefined) {
		const cell = cells[clientPercentageCol]
		const debt = debts.client_debt
		if (cell) {
			if (
				debt === 0 ||
				debt === '0' ||
				debt === '0 р.' ||
				debt === '0,00 р.' ||
				debt === '0.00'
			) {
				cell.classList.add('back-green')
			} else {
				cell.classList.remove('back-green')
			}
		}
	}
	if (profitCol !== -1 && debts.investor_debt !== undefined) {
		const cell = cells[profitCol]
		const debt = debts.investor_debt
		if (cell) {
			if (
				debt === 0 ||
				debt === '0' ||
				debt === '0 р.' ||
				debt === '0,00 р.' ||
				debt === '0.00'
			) {
				cell.classList.add('back-green')
			} else {
				cell.classList.remove('back-green')
			}
		}
	}
}

function showChangedCellsRow(row, changedCells) {
	const headers = row.closest('table').querySelectorAll('thead th')
	const columnIndexes = {}

	headers.forEach((header, index) => {
		const name = header.dataset.name
		if (name) {
			columnIndexes[name] = index
		}
	})

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
}

const setupSupplierAccountSelects = (isCollection = false) => {
	const findSelectByInput = ident => {
		const input =
			document.querySelector(`#${ident}`) ||
			document.querySelector(`[name="${ident}"]`)
		return input ? input.closest('.select') : null
	}

	const supplierSelect = findSelectByInput('supplier')
	const accountSelect = findSelectByInput('account')
	if (!accountSelect) return

	const supplierInput = supplierSelect?.querySelector('.select__input')
	const accountInput = accountSelect.querySelector('.select__input')
	const accountText = accountSelect.querySelector('.select__text')
	const accountDropdown = accountSelect.querySelector('.select__dropdown')
	const accountControl = accountSelect.querySelector('.select__control')

	if (
		typeof SelectHandler !== 'undefined' &&
		SelectHandler.setupSelectBehavior
	) {
		SelectHandler.setupSelectBehavior(accountSelect, null)
	}

	const clearAccountSelectionUI = () => {
		if (accountInput) accountInput.value = ''
		if (accountText) {
			accountText.textContent = accountInput?.getAttribute('placeholder') || ''
			accountText.classList.add('select__placeholder')
		}
		accountSelect.classList.remove('has-value')
	}

	let otherSuppliers = []
	fetch('/suppliers/list/others/')
		.then(res => res.json())
		.then(data => {
			otherSuppliers = data.map(s => String(s.id))
		})

	const selectVtbAccount = () => {
		const vtbOption = Array.from(
			accountDropdown.querySelectorAll('.select__option')
		).find(opt => opt.textContent.trim() === 'Р/с Втб')
		if (vtbOption) {
			accountInput.value = vtbOption.dataset.value
			accountText.textContent = vtbOption.textContent
			accountText.classList.remove('select__placeholder')
			accountSelect.classList.add('has-value')
			const event = new Event('change', { bubbles: true })
			accountInput.dispatchEvent(event)
		}
	}

	let loadToken = 0
	const loadAccountsForSupplier = async supplierId => {
		const myToken = ++loadToken

		SelectHandler.updateSelectOptions(accountSelect, [])

		if (!supplierId) return
		const url = `/accounts/list/?supplier_id=${encodeURIComponent(
			supplierId
		)}&is_collection=${isCollection}`
		const data = await SelectHandler.fetchSelectOptions(url)

		if (myToken !== loadToken) return
		SelectHandler.updateSelectOptions(accountSelect, data)

		requestAnimationFrame(() => {
			if (accountInput) {
				const currentVal =
					accountInput.value || accountInput.getAttribute('value')
				SelectHandler.restoreSelectValue(accountSelect, currentVal)
			}
			if (otherSuppliers.includes(String(supplierId))) {
				selectVtbAccount()
			}
		})
	}

	if (accountControl) {
		accountControl.addEventListener('click', async () => {
			if (accountDropdown?.hasChildNodes()) return
			const sid = supplierInput?.value
			await loadAccountsForSupplier(sid)
		})
	}

	if (supplierInput) {
		supplierInput.addEventListener('change', async () => {
			const sid = supplierInput.value
			clearAccountSelectionUI()
			await loadAccountsForSupplier(sid)
		})
	}

	const initialSupplierId = supplierInput?.value
	if (initialSupplierId) {
		loadAccountsForSupplier(initialSupplierId)
	} else {
		SelectHandler.updateSelectOptions(accountSelect, [])
	}
}

const setupMultipleSupplierAccountSelects = (pairs = []) => {
	pairs.forEach(({ supplierId, accountId }) => {
		const supplierSelect = document
			.querySelector(`#${supplierId}`)
			?.closest('.select')
		const accountSelect = document
			.querySelector(`#${accountId}`)
			?.closest('.select')
		if (!accountSelect) return

		const supplierInput = supplierSelect?.querySelector('.select__input')
		const accountInput = accountSelect.querySelector('.select__input')
		const accountText = accountSelect.querySelector('.select__text')
		const accountDropdown = accountSelect.querySelector('.select__dropdown')
		const accountControl = accountSelect.querySelector('.select__control')

		if (
			typeof SelectHandler !== 'undefined' &&
			SelectHandler.setupSelectBehavior
		) {
			SelectHandler.setupSelectBehavior(accountSelect, null)
		}

		const clearAccountSelectionUI = () => {
			if (accountInput) accountInput.value = ''
			if (accountText) {
				accountText.textContent =
					accountInput?.getAttribute('placeholder') || ''
				accountText.classList.add('select__placeholder')
			}
			accountSelect.classList.remove('has-value')
		}

		let loadToken = 0
		const loadAccountsForSupplier = async supplierId => {
			const myToken = ++loadToken

			SelectHandler.updateSelectOptions(accountSelect, [])

			if (!supplierId) return
			const url = `/accounts/list/?supplier_id=${encodeURIComponent(
				supplierId
			)}`
			const data = await SelectHandler.fetchSelectOptions(url)

			if (myToken !== loadToken) return
			SelectHandler.updateSelectOptions(accountSelect, data)

			requestAnimationFrame(() => {
				if (accountInput) {
					const currentVal =
						accountInput.value || accountInput.getAttribute('value')
					SelectHandler.restoreSelectValue(accountSelect, currentVal)
				}
			})
		}

		if (accountControl) {
			accountControl.addEventListener('click', async () => {
				if (accountDropdown?.hasChildNodes()) return
				const sid = supplierInput?.value
				await loadAccountsForSupplier(sid)
			})
		}

		if (supplierInput) {
			supplierInput.addEventListener('change', async () => {
				const sid = supplierInput.value
				clearAccountSelectionUI()
				await loadAccountsForSupplier(sid)
			})
		}

		const initialSupplierId = supplierInput?.value
		if (initialSupplierId) {
			loadAccountsForSupplier(initialSupplierId)
		} else {
			SelectHandler.updateSelectOptions(accountSelect, [])
		}
	})
}

function setupUserTypeBranchToggle() {
	const userTypeInput = document.getElementById('user_type')
	const branchGroup = document.getElementById('branch-group')
	if (!userTypeInput || !branchGroup) return

	function toggleBranch() {
		const value = userTypeInput.value
		const selectedText = Array.from(
			document.querySelectorAll('.select__option[data-value]')
		)
			.find(opt => opt.dataset.value === value)
			?.textContent?.trim()
		if (selectedText === 'Филиал') {
			branchGroup.removeAttribute('hidden')
		} else {
			branchGroup.setAttribute('hidden', 'true')
		}
	}

	userTypeInput.addEventListener('change', toggleBranch)

	const userTypeSelect = userTypeInput.closest('.select')
	if (userTypeSelect) {
		userTypeSelect.addEventListener('click', function (e) {
			const option = e.target.closest('.select__option')
			if (option) {
				userTypeInput.value = option.dataset.value
				toggleBranch()
			}
		})
	}

	toggleBranch()
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
			const res = await fetch(
				`${this.baseUrl}${this.entityName}/list/?page=${page}`
			)
			if (!res.ok) {
				let errBody = { message: `HTTP error! status: ${res.status}` }
				try {
					errBody = await res.json()
				} catch (e) {}
				this.handleError(errBody, res)
				return
			}

			const data = await res.json()

			if (res.ok && data.html && data.context) {
				TableManager.updateTable(data.html, this.tableId)

				try {
					const filters = TableManager.getTableFilters(this.tableId)
					if (filters && filters.size > 0) {
						const tableEl = document.getElementById(this.tableId)
						if (tableEl) {
							TableManager.applyFilters(tableEl, filters)
						}
					}
				} catch (e) {
					console.warn(
						'Ошибка при применении клиентских фильтров после пагинации:',
						e
					)
				}

				this.updatePagination(data.context)
				this.onDataLoaded(data)
			} else {
				this.handleError(data, res)
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

		if (!response.ok) {
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

		setupSupplierAccountSelects()
	},

	addFunc: () => {
		setupCurrencyInput('amount')
		setupPercentInput('client_percentage')
		setupPercentInput('supplier_percentage')
		setupPercentInput('bonus_percentage')

		setupSupplierAccountSelects()
	},

	afterAddFunc: result => {
		refreshData(`${TRANSACTION}-table`, result.id)
		const row = TableManager.getRowById(result.id, `${TRANSACTION}-table`)
		TableManager.formatCurrencyValuesForRow(`${TRANSACTION}-table`, row)

		const table = document.getElementById(`${TRANSACTION}-table`)
		const hasProfitColumn =
			table && table.querySelector('th[data-name="profit"]')

		if (hasProfitColumn) {
			TableManager.calculateTableSummary(`${TRANSACTION}-table`, ['profit'], {
				grouped: true,
				total: true,
			})
		}

		colorizeRemainingAmountByDebtsRow(row, result.debts)
		showChangedCellsRow(row, result.changed_cells)
	},
	afterEditFunc: result => {
		refreshData(`${TRANSACTION}-table`)
		const row = TableManager.getRowById(result.id, `${TRANSACTION}-table`)
		TableManager.formatCurrencyValuesForRow(`${TRANSACTION}-table`, row)

		const table = document.getElementById(`${TRANSACTION}-table`)
		const hasProfitColumn =
			table && table.querySelector('th[data-name="profit"]')

		if (hasProfitColumn) {
			TableManager.calculateTableSummary(`${TRANSACTION}-table`, ['profit'], {
				grouped: true,
				total: true,
			})
		}

		colorizeRemainingAmountByDebtsRow(row, result.debts)
		showChangedCellsRow(row, result.changed_cells)
	},
	afterDeleteFunc: () => {
		const table = document.getElementById(`${TRANSACTION}-table`)
		const hasProfitColumn =
			table && table.querySelector('th[data-name="profit"]')

		if (hasProfitColumn) {
			TableManager.calculateTableSummary(`${TRANSACTION}-table`, ['profit'], {
				grouped: true,
				total: true,
			})
		}
	},
	modalConfig: {
		addModalUrl: '/components/main/add_transaction/',
		editModalUrl: '/components/main/add_transaction/',
		addModalTitle: 'Добавить сделку',
		editModalTitle: 'Редактировать сделку',
	},
})

const suppliersConfig = createConfig(SUPPLIERS, {
	dataUrls: [
		{ id: 'account_ids', url: `${BASE_URL}accounts/list/` },
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

const usersConfig = createConfig('users', {
	dataUrls: [
		{ id: 'user_type', url: `${BASE_URL}users/types/` },
		{ id: 'branch', url: `${BASE_URL}branches/list/` },
	],
	addFunc: () => {
		setupUserTypeBranchToggle()
	},
	editFunc: () => {
		setupUserTypeBranchToggle()
	},
	afterAddFunc: result => refreshData(`users-table`, result.id),
	afterEditFunc: result => refreshData(`users-table`),
	modalConfig: {
		addModalUrl: '/components/main/add_user/',
		editModalUrl: '/components/main/add_user/',
		addModalTitle: 'Добавить пользователя',
		editModalTitle: 'Редактировать пользователя',
	},
})

const clientsConfig = createConfig(CLIENTS, {
	editFunc: () => {
		setupPercentInput('percentage')
		setupPercentInput('bonus_percentage')
	},
	addFunc: () => {
		setupPercentInput('percentage')
		setupPercentInput('bonus_percentage')
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
		{ id: 'purpose', url: `${BASE_URL}payment_purposes/list/` },
		{ id: 'supplier', url: `${BASE_URL}${SUPPLIERS}/list/` },
	],
	editFunc: () => {
		setupCurrencyInput('amount')
		checkOperationType()
		setupSupplierAccountSelects()

		const purposeInput = document.getElementById('purpose')
		if (purposeInput) {
			const selectContainer = purposeInput.closest('.select')
			const control = selectContainer?.querySelector('.select__control')
			if (control) {
				control.addEventListener('click', async () => {
					try {
						const response = await fetch('/payment_purpose/types/')
						if (!response.ok) return
						const types = await response.json()
						const options = selectContainer.querySelectorAll('.select__option')
						options.forEach(option => {
							option.classList.remove('text-red', 'text-green')
							const typeObj = types.find(
								t => String(t.id) === option.dataset.value
							)

							if (typeObj) {
								if (typeObj.operation_type === 'expense') {
									option.classList.add('text-red')
								} else if (typeObj.operation_type === 'income') {
									option.classList.add('text-green')
								}
							}
						})
					} catch (e) {}
				})
			}
		}

		const createdAtInput = document.getElementById('created_at_formatted')
		if (createdAtInput) {
			createdAtInput.removeAttribute('hidden')
		}
	},
	addFunc: () => {
		setupCurrencyInput('amount')
		checkOperationType()
		setupSupplierAccountSelects()

		const purposeInput = document.getElementById('purpose')
		if (purposeInput) {
			const selectContainer = purposeInput.closest('.select')
			const control = selectContainer?.querySelector('.select__control')
			if (control) {
				control.addEventListener('click', async () => {
					try {
						const response = await fetch('/payment_purpose/types/')
						if (!response.ok) return
						const types = await response.json()
						const options = selectContainer.querySelectorAll('.select__option')
						options.forEach(option => {
							option.classList.remove('text-red', 'text-green')
							const typeObj = types.find(
								t => String(t.id) === option.dataset.value
							)

							if (typeObj) {
								if (typeObj.operation_type === 'expense') {
									option.classList.add('text-red')
								} else if (typeObj.operation_type === 'income') {
									option.classList.add('text-green')
								}
							}
						})
					} catch (e) {}
				})
			}
		}
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
		addModalTitle: 'Добавить сделку',
		editModalTitle: 'Редактировать сделку',
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
		addModalTitle: 'Добавить сделку',
		editModalTitle: 'Редактировать сделку',
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

const settleDebtAllFormHandler = createFormHandler(
	`${BASE_URL}${SUPPLIERS}/close_investor_debt/`,
	'summary-profit',
	'settle-debt-form',
	`/suppliers/debtors/transactions.investors/`,
	[
		{
			id: 'investor_select',
			url: `${BASE_URL}investors/list/`,
		},
	],
	{
		url: '/components/main/settle-debt/',
		title: 'Погасить все долги инвесторам',
	},
	async result => {
		const table = document.getElementById('summary-profit')
		if (!table) return

		if (Array.isArray(result.closed)) {
			result.closed.forEach(obj => {
				const row = table.querySelector(`tr[data-id="${obj.id}"]`)
				if (row) {
					row.classList.add('hidden-row', 'row-done')
				}
			})
		}

		if (Array.isArray(result.changed_html_rows)) {
			result.changed_html_rows.forEach(({ id, html }) => {
				TableManager.updateTableRow({ html, id }, 'summary-profit')
				const row = TableManager.getRowById(id, 'summary-profit')
				TableManager.formatCurrencyValuesForRow('summary-profit', row)
			})
		}

		if (result.html_investor_debt_operation) {
			const tableOps = document.getElementById('investor-operations-table')
			if (tableOps) {
				const wrapper = document.createElement('tbody')
				wrapper.innerHTML = result.html_investor_debt_operation
				const newRow = wrapper.querySelector('tr')
				if (newRow) {
					tableOps.querySelector('tbody').appendChild(newRow)
					TableManager.formatCurrencyValuesForRow(
						'investor-operations-table',
						newRow
					)
				}
			}
		}

		if (result.html_investor_row && result.investor_id) {
			const investorsTable = document.getElementById('investors-table')
			if (investorsTable) {
				TableManager.updateTableRow(
					{ html: result.html_investor_row, id: result.investor_id },
					'investors-table'
				)
				const investorRow = TableManager.getRowById(
					result.investor_id,
					'investors-table'
				)
				TableManager.formatCurrencyValuesForRow('investors-table', investorRow)

				TableManager.calculateTableSummary('investors-table', ['balance'])
			}
		}
	}
)

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
		const row = TableManager.getRowById(result.id, `${TRANSACTION}-table`)
		TableManager.formatCurrencyValuesForRow(`${TRANSACTION}-table`, row)

		if (result.changed_cells) {
			showChangedCellsRow(row, result.changed_cells)
		}
		if (result.debts) {
			colorizeRemainingAmountByDebtsRow(row, result.debts)
		}
	}
)

const collectionFormHandler = createFormHandler(
	`${BASE_URL}money_transfers/collection/`,
	'suppliers-account-table',
	`collection-form`,
	[],
	[{ id: 'supplier', url: `${BASE_URL}${SUPPLIERS}/list/` }],
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
			TableManager.formatCurrencyValuesForRow('suppliers-account-table', row)
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

		if (
			result.cash_balance !== undefined &&
			result.grand_total_with_cash !== undefined
		) {
			const cashBalanceDisplay = document.getElementById('cash-balance-display')
			const grandTotalWithCashDisplay = document.getElementById(
				'grand-total-with-cash-display'
			)
			if (cashBalanceDisplay) {
				cashBalanceDisplay.textContent = formatAmountString(result.cash_balance)
			}
			if (grandTotalWithCashDisplay) {
				grandTotalWithCashDisplay.textContent = formatAmountString(
					result.grand_total_with_cash
				)
			}
		}
	}
)

const moneyTransfersFormHandler = createFormHandler(
	`${BASE_URL}${MONEY_TRANSFERS}/add/`,
	'suppliers-account-table',
	'money_transfers-form',
	[],
	[
		{ id: 'source_supplier', url: `${BASE_URL}${SUPPLIERS}/list/` },
		{ id: 'destination_supplier', url: `${BASE_URL}${SUPPLIERS}/list/` },
	],
	{
		url: '/components/main/add_money_transfers/',
		title: 'Перевод денег',
		...(mainConfig.modalConfig.context
			? { context: mainConfig.modalConfig.context }
			: {}),
	},
	result => {
		if (result.table_html) {
			const table = document.getElementById('suppliers-account-table')
			if (table) {
				const wrapper = document.createElement('div')
				wrapper.innerHTML = result.table_html
				const newTable = wrapper.querySelector('table')
				if (newTable) {
					table.parentNode.replaceChild(newTable, table)
					TableManager.init()
					handleSupplierAccounts()
				}
			}
		}

		if (
			result.cash_balance !== undefined &&
			result.grand_total_with_cash !== undefined
		) {
			const cashBalanceDisplay = document.getElementById('cash-balance-display')
			const grandTotalWithCashDisplay = document.getElementById(
				'grand-total-with-cash-display'
			)
			if (cashBalanceDisplay) {
				cashBalanceDisplay.textContent = formatAmountString(result.cash_balance)
			}
			if (grandTotalWithCashDisplay) {
				grandTotalWithCashDisplay.textContent = formatAmountString(
					result.grand_total_with_cash
				)
			}
		}
	}
)

const updateBalanceSpans = data => {
	try {
		const headers = Array.from(
			document.querySelectorAll('#balance-container .debtors-header')
		)
		if (headers.length >= 2) {
			const assetsSpan = headers[0].querySelector('.debtors-total')
			const liabilitiesSpan = headers[1].querySelector('.debtors-total')
			if (assetsSpan && data.assets !== undefined)
				assetsSpan.textContent = formatAmount(data.assets)
			if (liabilitiesSpan && data.liabilities !== undefined)
				liabilitiesSpan.textContent = formatAmount(data.liabilities)
		}

		const setItemTotalByTitle = (title, value) => {
			const titleNodes = Array.from(
				document.querySelectorAll('.debtors-office-list__title')
			)
			const node = titleNodes.find(n => n.textContent.trim() === title)
			if (node) {
				const amountSpan = node.parentElement.querySelector(
					'.debtors-office-list__amount'
				)
				if (amountSpan) amountSpan.textContent = formatAmount(value)
			}
		}

		if (data.inventory_total !== undefined)
			setItemTotalByTitle('ТМЦ', data.inventory_total)
		if (data.credit_total !== undefined)
			setItemTotalByTitle('Кредит', data.credit_total)
		if (data.short_term_total !== undefined)
			setItemTotalByTitle('Краткосрочные обязательства', data.short_term_total)
		if (data.capital !== undefined) setItemTotalByTitle('Капитал', data.capital)
	} catch (e) {
		console.error('updateBalanceSpans error', e)
	}
}

const insertRowToTable = (tableId, html, newId) => {
	try {
		if (!html) return
		TableManager.addTableRow({ html }, tableId)
		if (newId) setLastRowId(newId, tableId)
		TableManager.formatCurrencyValues(tableId)
	} catch (e) {
		console.error('insertRowToTable error', e)
	}
}

const balanceFormHandler = createFormHandler(
	'/balance_items/add/',
	'',
	'cash_flow-form',
	[],
	[],
	{
		url: '/components/main/add_balance_item/',
		title: 'Добавить элемент баланса',
	},
	result => {
		if (!result) return
		if (result.status !== 'success') {
			showError(result.message || 'Ошибка добавления')
			return
		}

		if (result.type === 'inventory') {
			insertRowToTable('inventory-table', result.html, result.id)
		} else if (result.type === 'credit') {
			insertRowToTable('credits-table', result.html, result.id)
		} else if (
			result.type === 'short_term' ||
			result.type === 'short_term_liability'
		) {
			insertRowToTable('short-term-table', result.html, result.id)
		}

		updateBalanceSpans(result)
	}
)

const balanceEditFormHandler = createFormHandler(
	`${BASE_URL}balance_items/edit/`,
	'',
	'cash_flow-form',
	`${BASE_URL}balance_items/`,
	[],
	{
		url: '/components/main/add_balance_item/',
		title: 'Редактировать элемент баланса',
	},
	result => {
		if (!result) return
		if (result.status !== 'success') {
			showError(result.message || 'Ошибка изменения')
			return
		}

		const targetTable =
			result.type === 'inventory'
				? 'inventory-table'
				: result.type === 'credit'
				? 'credits-table'
				: result.type === 'short_term' || result.type === 'short_term_liability'
				? 'short-term-table'
				: null

		;['inventory-table', 'credits-table', 'short-term-table'].forEach(tid => {
			if (tid === targetTable) return
			const row = document.querySelector(`#${tid} tr[data-id="${result.id}"]`)
			if (row) row.remove()
		})

		if (targetTable) {
			const existingRow = document.querySelector(
				`#${targetTable} tr[data-id="${result.id}"]`
			)
			if (existingRow) {
				TableManager.updateTableRow(
					{ html: result.html, id: result.id },
					targetTable
				)
			} else {
				TableManager.addTableRow({ html: result.html }, targetTable)
				setLastRowId(result.id, targetTable)
			}
			const row = TableManager.getRowById(result.id, targetTable)
			TableManager.formatCurrencyValuesForRow(targetTable, row)
		}

		updateBalanceSpans(result)
	}
)

function initBalanceAddButton() {
	const addButton = document.getElementById('add-button')
	if (!addButton) return

	addButton.addEventListener('click', async function (e) {
		const selectedCell = document.querySelector('td.table__cell--selected')
		const table = selectedCell ? selectedCell.closest('table') : null
		let type = 'inventory'

		if (table) {
			if (table.id === 'inventory-table') {
				type = 'inventory'
			} else if (table.id === 'credits-table' || table.id === 'credit-table') {
				type = 'credit'
			} else if (table.id === 'short-term-table') {
				type = 'short_term'
			}
		}

		balanceFormHandler.config.modalConfig.title =
			'Добавить ' +
			(type === 'inventory'
				? 'ТМЦ'
				: type === 'credit'
				? 'Кредит'
				: 'Краткосрочное обязательство')

		await balanceFormHandler.init(0)

		const form = document.getElementById('cash_flow-form')
		if (!form) {
			showError('Форма добавления недоступна')
			return
		}

		let typeInput = form.querySelector('#operation_type')

		if (!typeInput) {
			typeInput = document.createElement('input')
			typeInput.type = 'hidden'
			typeInput.id = 'operation_type'
			typeInput.name = 'operation_type'
			form.appendChild(typeInput)
		}
		typeInput.value = type

		const quantity = form.querySelector('#quantity') || null
		const price = form.querySelector('#price') || null
		const amountInput = form.querySelector('#amount')
		const quantityInput = form.querySelector('#quantity')
		const priceInput = form.querySelector('#price')
		const nameInput = form.querySelector('#name')

		if (quantity) quantity.hidden = true
		if (price) price.hidden = true
		if (quantityInput) quantityInput.value = ''
		if (priceInput) priceInput.value = ''
		if (amountInput) {
			amountInput.readOnly = false
			amountInput.placeholder = 'Введите сумму'
			amountInput.value = ''
		}

		if (type === 'inventory') {
			if (quantity) quantity.hidden = false
			if (price) price.hidden = false
			if (amountInput) {
				amountInput.placeholder = 'Сумма'
				amountInput.readOnly = true
			}
			setupCurrencyInput('price')
			setupCurrencyInput('amount')

			const recalcAmount = () => {
				const qv = quantityInput
					? (quantityInput.value || '').replace(',', '.')
					: '0'
				let qty = Number(qv)
				if (isNaN(qty)) qty = 0
				let priceVal = 0
				if (priceInput && priceInput.autoNumeric) {
					priceVal = Number(priceInput.autoNumeric.getNumericString() || 0)
				} else {
					priceVal =
						Number(
							(priceInput ? priceInput.value || 0 : 0)
								.toString()
								.replace(/\s/g, '')
								.replace(',', '.')
						) || 0
				}
				const total = qty * priceVal
				if (amountInput && amountInput.autoNumeric) {
					amountInput.autoNumeric.set(total || 0)
				} else if (amountInput) {
					amountInput.value = total ? String(total) : ''
				}
			}
			quantityInput?.addEventListener('input', recalcAmount)
			priceInput?.addEventListener('input', recalcAmount)
		} else {
			if (amountInput) {
				amountInput.readOnly = false
				amountInput.placeholder = 'Введите сумму'
			}
			setupCurrencyInput('amount')
		}

		nameInput?.focus()
	})
}

function initBalanceEditButton() {
	const editBtn = document.getElementById('edit-button')
	if (editBtn) {
		editBtn.addEventListener('click', async function (e) {
			e.preventDefault()
			const selectedCell = document.querySelector('td.table__cell--selected')
			const table = selectedCell ? selectedCell.closest('table') : null
			const tableId = table ? table.id : null
			const id = TableManager.getSelectedRowId(tableId)

			if (!id) {
				showError('Выберите строку для редактирования')
				return
			}

			if (tableId === 'inventory-table') {
				balanceEditFormHandler.config.getUrl = `${BASE_URL}balance_items/inventory/`
			} else if (tableId === 'credits-table' || tableId === 'credit-table') {
				balanceEditFormHandler.config.getUrl = `${BASE_URL}balance_items/credit/`
			} else if (tableId === 'short-term-table') {
				balanceEditFormHandler.config.getUrl = `${BASE_URL}balance_items/short_term/`
			} else {
				showError('Выберите строку для редактирования')
				return
			}

			await balanceEditFormHandler.init(id)

			const form = document.getElementById('cash_flow-form')
			if (!form) return

			let type = 'inventory'
			if (tableId === 'inventory-table') type = 'inventory'
			else if (tableId === 'credits-table' || tableId === 'credit-table')
				type = 'credit'
			else if (tableId === 'short-term-table') type = 'short_term'

			let typeInput = form.querySelector('#operation_type')
			if (!typeInput) {
				typeInput = document.createElement('input')
				typeInput.type = 'hidden'
				typeInput.id = 'operation_type'
				typeInput.name = 'operation_type'
				form.appendChild(typeInput)
			}
			typeInput.value = type

			const quantity = form.querySelector('#quantity') || null
			const price = form.querySelector('#price') || null
			const amountInput = form.querySelector('#amount')
			const quantityInput = form.querySelector('#quantity')
			const priceInput = form.querySelector('#price')
			const nameInput = form.querySelector('#name')

			if (quantity) quantity.hidden = type !== 'inventory'
			if (price) price.hidden = type !== 'inventory'

			if (type === 'inventory') {
				if (quantity) quantity.hidden = false
				if (price) price.hidden = false
				if (amountInput) {
					amountInput.placeholder = 'Сумма'
					amountInput.readOnly = true
				}
				setupCurrencyInput('price')
				setupCurrencyInput('amount')

				const recalcAmount = () => {
					const qv = quantityInput
						? (quantityInput.value || '').replace(',', '.')
						: '0'
					let qty = Number(qv)
					if (isNaN(qty)) qty = 0
					let priceVal = 0
					if (priceInput && priceInput.autoNumeric) {
						priceVal = Number(priceInput.autoNumeric.getNumericString() || 0)
					} else {
						priceVal =
							Number(
								(priceInput ? priceInput.value || 0 : 0)
									.toString()
									.replace(/\s/g, '')
									.replace(',', '.')
							) || 0
					}
					const total = qty * priceVal
					if (amountInput && amountInput.autoNumeric) {
						amountInput.autoNumeric.set(total || 0)
					} else if (amountInput) {
						amountInput.value = total ? String(total) : ''
					}
				}
				quantityInput?.addEventListener('input', recalcAmount)
				priceInput?.addEventListener('input', recalcAmount)
			} else {
				if (amountInput) {
					amountInput.readOnly = false
					amountInput.placeholder = 'Введите сумму'
					setupCurrencyInput('amount')
				}
			}

			nameInput?.focus()
		})
	}
}

function initBalanceDeleteButton() {
	const deleteBtn = document.getElementById('delete-button')
	if (!deleteBtn) return

	deleteBtn.addEventListener('click', async function (e) {
		e.preventDefault()
		const selectedCell = document.querySelector('td.table__cell--selected')
		const table = selectedCell ? selectedCell.closest('table') : null
		const tableId = table ? table.id : null
		const id = TableManager.getSelectedRowId(tableId)

		if (!id) {
			showError('Выберите строку для удаления')
			return
		}

		let operation_type = 'inventory'
		if (tableId === 'inventory-table') operation_type = 'inventory'
		else if (tableId === 'credits-table' || tableId === 'credit-table')
			operation_type = 'credit'
		else if (tableId === 'short-term-table') operation_type = 'short_term'
		else operation_type = 'balance'

		showQuestion(
			'Вы действительно хотите удалить запись?',
			'Удаление',
			async () => {
				const loader = createLoader()
				document.body.appendChild(loader)
				try {
					const url = `${BASE_URL}balance_items/delete/${id}/`
					const res = await fetch(url, {
						method: 'POST',
						headers: {
							'X-CSRFToken': getCSRFToken(),
							'Content-Type': 'application/json',
						},
						body: JSON.stringify({ operation_type: operation_type }),
					})

					if (!res.ok) {
						let err = { message: `HTTP error! status: ${res.status}` }
						try {
							err = await res.json()
						} catch (e) {}
						throw new Error(err.message || 'Ошибка удаления')
					}

					const data = await res.json()
					if (!data || data.status !== 'success') {
						showError(data?.message || 'Не удалось удалить запись')
						return
					}

					const row = document.querySelector(`#${tableId} tr[data-id="${id}"]`)
					if (row) {
						row.remove()
					} else {
						document
							.querySelectorAll(`tr[data-id="${id}"]`)
							.forEach(r => r.remove())
					}

					try {
						if (tableId) {
							TableManager.formatCurrencyValues(tableId)
						}
					} catch (err) {}

					try {
						updateBalanceSpans(data)
					} catch (err) {}
				} catch (err) {
					console.error('Ошибка при удалении элемента баланса:', err)
					showError(err.message || 'Ошибка при удалении')
				} finally {
					const loaderEl = document.querySelector('.loader')
					if (loaderEl) loaderEl.remove()
				}
			}
		)
	})
}

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
		const debtsData = document.getElementById('debts')?.textContent
		if (debtsData) {
			const debts = JSON.parse(debtsData)
			supplierDebtsAll = debts || []
			colorizeRemainingAmountByDebts(debts)

			hideCompletedTransactions(debts)
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
			const table = document.getElementById(`${TRANSACTION}-table`)
			const hasProfitColumn =
				table && table.querySelector('th[data-name="profit"]')

			if (hasProfitColumn) {
				TableManager.calculateTableSummary(`${TRANSACTION}-table`, ['profit'], {
					grouped: true,
					total: true,
				})
			}
		},
	})

	const table = document.getElementById(`${TRANSACTION}-table`)
	const hasProfitColumn = table && table.querySelector('th[data-name="profit"]')

	if (hasProfitColumn) {
		TableManager.calculateTableSummary(`${TRANSACTION}-table`, ['profit'], {
			grouped: true,
			total: true,
		})
	}

	TableManager.createColumnsForTable(
		'transactions-table',
		[
			{ name: 'created_at' },
			{ name: 'client', url: '/clients/list/' },
			{ name: 'supplier', url: '/suppliers/list/' },
			{ name: 'account', url: '/accounts/list/' },
			{ name: 'amount' },
			{ name: 'client_percentage' },
			{ name: 'supplier_percentage' },
			{ name: 'bonus_percentage' },
			{ name: 'remaining_amount' },
			{ name: 'profit' },
			{ name: 'bonus' },
			{ name: 'paid_amount' },
			{ name: 'debt' },
			{ name: 'documents' },
		],
		['profit']
	)

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
	const tableId = `${TRANSACTION}-table`

	if (hideButton) {
		hideButton.addEventListener('click', function () {
			const rowId = TableManager.getSelectedRowId(`${TRANSACTION}-table`)
			if (rowId) {
				toggleTransactionVisibility(rowId)
				saveHiddenRowsState(tableId)
			}
		})
	}

	if (showAllButton) {
		showAllButton.addEventListener('click', function () {
			toggleAllTransactions(true, supplierDebtsAll)
			saveShowAllState(tableId)
		})
	}

	if (hideAllButton) {
		hideAllButton.addEventListener('click', function () {
			toggleAllTransactions(false, supplierDebtsAll)
			saveHiddenRowsState(tableId)
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

const handleUsers = async config => {
	try {
		const usersIdsData = document.getElementById('data-ids')?.textContent
		if (usersIdsData) {
			const usersIds = JSON.parse(usersIdsData)
			setIds(usersIds, `users-table`)
		} else {
			console.warn("Element with ID 'data-ids' not found or empty.")
		}
	} catch (e) {
		console.error('Error parsing users IDs data for actions column:', e)
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

	try {
		const summaryContainer = document.getElementById('summary-container')
		if (summaryContainer) {
			const moneyLogsPaginator = new TablePaginator({
				baseUrl: BASE_URL,
				entityName: 'money_logs',
				tableId: 'money-logs-table',
				onDataLoaded: data => {
					const ctx = data.context || {}
					if (Array.isArray(ctx.money_log_ids)) {
						setIds(ctx.money_log_ids, 'money-logs-table')
					}

					TableManager.initTable('money-logs-table')
					try {
						const table = document.getElementById('money-logs-table')
						if (table) {
							const headers = table.querySelectorAll('thead th')
							let amountCol = -1
							headers.forEach((th, idx) => {
								if (th.dataset.name === 'amount') amountCol = idx
							})
							if (amountCol !== -1) {
								const rows = table.querySelectorAll('tbody tr')
								rows.forEach(row => {
									const cells = row.querySelectorAll('td')
									if (cells.length > amountCol) {
										const cell = cells[amountCol]
										let value = cell.textContent
											.replace(/\s/g, '')
											.replace('р.', '')
											.replace('р', '')
											.replace(',', '.')
										let num = Number(value)
										if (!isNaN(num)) {
											if (num < 0) {
												cell.classList.add('text-red')
												cell.classList.remove('text-green')
											} else {
												cell.classList.add('text-green')
												cell.classList.remove('text-red')
											}
										}
									}
								})
							}
						}
					} catch (e) {
						console.error('Ошибка при подсветке money-logs:', e)
					}
				},
			})

			await moneyLogsPaginator.goToPage(moneyLogsPaginator.currentPage || 1)

			if (!document.getElementById('refresh-money-logs-btn')) {
				const refreshBtn = document.createElement('button')
				refreshBtn.id = 'refresh-money-logs-btn'
				refreshBtn.className = 'refresh-money-logs-btn'
				refreshBtn.title = 'Обновить'
				refreshBtn.innerHTML = `<img src="/static/images/arrows-rotate.svg" alt="Обновить" height="16" width="16">`

				refreshBtn.addEventListener('click', async () => {
					try {
						refreshBtn.disabled = true
						await moneyLogsPaginator.goToPage(
							moneyLogsPaginator.currentPage || 1
						)
					} catch (e) {
						console.error('Ошибка при обновлении money-logs:', e)
					} finally {
						refreshBtn.disabled = false
					}
				})

				summaryContainer.appendChild(refreshBtn)
			}
		}
	} catch (e) {
		const summaryContainer = document.getElementById('summary-container')
		if (summaryContainer) {
			summaryContainer.innerHTML =
				'<div class="error">Ошибка загрузки логов</div>'
		}
		console.error('Ошибка загрузки money_logs:', e)
	}

	const cashBalanceDisplay = document.getElementById('cash-balance-display')
	const grandTotalWithCashDisplay = document.getElementById(
		'grand-total-with-cash-display'
	)

	if (!cashBalanceDisplay && !grandTotalWithCashDisplay) {
		try {
			const cash_balance = document.getElementById('cash-balance')?.textContent
			const grand_total_with_cash = document.getElementById(
				'grand-total-with-cash'
			)?.textContent
			const table = document.getElementById('suppliers-account-table')
			if (cash_balance && grand_total_with_cash && table) {
				const cashBalance = JSON.parse(cash_balance)
				const grandTotalWithCash = JSON.parse(grand_total_with_cash)

				const summaryBlock = document.createElement('div')
				summaryBlock.className = 'account-summary-block'
				summaryBlock.innerHTML = `
            <div class="account-summary-row">
                <span class="account-summary-label">Наличные:</span>
                <span class="account-summary-value" id="cash-balance-display"
				>${formatAmountString(cashBalance)}</span>
            </div>
            <div class="account-summary-row">
                <span class="account-summary-label">Итого:</span>
                <span class="account-summary-value" id="grand-total-with-cash-display"
				>${formatAmountString(grandTotalWithCash)}</span>
            </div>
        `

				table.parentNode.insertBefore(summaryBlock, table.nextSibling)
			} else {
				console.warn("Element with ID 'account-ids' not found or empty.")
			}
		} catch (e) {
			console.error('Error parsing account IDs data for actions column:', e)
		}
	}

	const collectionButton = document.getElementById('collection-button')
	if (collectionButton && !collectionButton.dataset.listenerAdded) {
		collectionButton.addEventListener('click', async function (e) {
			await collectionFormHandler.init(0)

			setupSupplierAccountSelects(true)

			setupCurrencyInput('amount')

			collectionButton.dataset.listenerAdded = 'true'
		})
	}

	const moneyTransfersButton = document.getElementById('add-button')
	if (moneyTransfersButton && !moneyTransfersButton.dataset.listenerAdded) {
		moneyTransfersButton.addEventListener('click', async function (e) {
			await moneyTransfersFormHandler.init(0)

			setupMultipleSupplierAccountSelects([
				{ supplierId: 'source_supplier', accountId: 'source_account' },
				{
					supplierId: 'destination_supplier',
					accountId: 'destination_account',
				},
			])

			setupCurrencyInput('amount')

			moneyTransfersButton.dataset.listenerAdded = 'true'
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

	await TableManager.createColumnsForTable(
		'cash_flow-table',
		[
			{ name: 'created_at' },
			{ name: 'account', url: '/accounts/list/' },
			{ name: 'supplier', url: '/suppliers/list/' },
			{ name: 'formatted_amount' },
			{ name: 'purpose', url: '/payment_purposes/list/?all=True' },
			{ name: 'comment' },
			{ name: 'created_by', url: '/users/list/' },
		],
		['profit']
	)

	const urlParams = new URLSearchParams(window.location.search)
	const idPurpose = urlParams.get('id_purpose')
	const createdAt = urlParams.get('created_at')

	if (idPurpose || createdAt) {
		if (createdAt) {
			const createdAtInput = document.querySelector('input[name="created_at"]')

			if (createdAtInput) {
				createdAtInput.value = createdAt
				createdAtInput.dispatchEvent(new Event('input', { bubbles: true }))
			}
		}

		const selectInput = document.getElementById('id_purpose')
		const select = selectInput ? selectInput.closest('.select') : null
		const selectControl = select
			? select.querySelector('.select__control')
			: null

		if (
			select &&
			selectControl &&
			idPurpose &&
			idPurpose !== 0 &&
			idPurpose !== '0'
		) {
			selectControl.click()

			const trySelectOption = () => {
				const option = select.querySelector(
					`.select__option[data-value="${idPurpose}"]`
				)
				if (option) {
					option.click()
				} else {
					setTimeout(trySelectOption, 100)
				}
			}
			trySelectOption()
		}
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

	const selectInput = document.getElementById('supplier_stats')
	const select = selectInput.closest('.select')

	SelectHandler.setupSelects({
		select: select,
		url: '/suppliers/list/',
	})

	document.addEventListener('click', function (e) {
		const option = e.target.closest('.select__option')
		if (option && select.contains(option)) {
			const supplierId = option.dataset.value
			if (!supplierId) return

			fetch(`/cash_flow/payment_stats/${supplierId}/`)
				.then(res => res.json())
				.then(data => {
					const chartElem = document.getElementById('statsChart')
					if (!chartElem) return
					const ctx = chartElem.getContext('2d')
					if (window.supplierChart) {
						window.supplierChart.destroy()
					}

					function getNiceMax(value) {
						if (value <= 10) return 10
						if (value <= 100) return Math.ceil(value / 10) * 10
						if (value <= 1000) return Math.ceil(value / 100) * 100
						if (value <= 10000) return Math.ceil(value / 500) * 500
						if (value <= 100000) return Math.ceil(value / 1000) * 1000
						if (value <= 1000000) return Math.ceil(value / 50000) * 50000
						return Math.ceil(value / 100000) * 100000
					}

					const maxValue = Math.max(...data.values)
					const yMax = getNiceMax(maxValue * 1.1)

					window.supplierChart = new Chart(ctx, {
						type: 'bar',
						data: {
							labels: data.months,
							datasets: [
								{
									label: '',
									data: data.values,
									backgroundColor: 'rgba(54, 162, 235, 0.5)',
									borderColor: 'rgba(54, 162, 235, 1)',
									borderWidth: 1,
									stepped: true,
								},
							],
						},
						options: {
							scales: {
								y: {
									beginAtZero: true,
									max: yMax,
								},
							},
							plugins: {
								legend: { display: false },
								tooltip: {
									enabled: false,
								},
								datalabels: {
									anchor: 'end',
									align: 'end',
									font: { size: 10, weight: 'bold' },
									color: '#1976d2',
									formatter: value => value.toLocaleString('ru-RU') + ' р.',
								},
							},
						},
						plugins: [ChartDataLabels],
					})
				})
		}
	})
}

const handleReport = () => {
	try {
		const dataIdsData = document.getElementById('data-ids')?.textContent
		if (dataIdsData) {
			const dataIds = JSON.parse(dataIdsData)
			setIds(dataIds, `cash_flow_report-table`)
		} else {
			console.warn("Element with ID 'data-ids' not found or empty.")
		}
	} catch (e) {
		console.error(
			'Error parsing money transfers IDs data for actions column:',
			e
		)
	}

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

		const detailButton = document.getElementById('detail-button')
		if (detailButton) {
			detailButton.addEventListener('click', function () {
				const selectedRow = document.querySelector(
					'#cash_flow_report-table tr.table__row--selected'
				)
				const selectedCell = document.querySelector(
					'#cash_flow_report-table td.table__cell--selected'
				)
				let query = ''
				if (selectedRow) {
					const idPurpose = selectedRow.getAttribute('data-id')
					const table = document.getElementById('cash_flow_report-table')
					const rows = table.querySelectorAll('tbody tr')
					const cells = selectedRow.querySelectorAll('td')
					const isTotalRow = selectedRow.classList.contains('total-row')
					let isLastCell = false
					let createdAt = null

					if (selectedCell && !isTotalRow) {
						const cellIndex = Array.from(
							selectedCell.parentNode.children
						).indexOf(selectedCell)
						isLastCell = cellIndex === cells.length - 1
						if (cellIndex > 0 && !isLastCell) {
							const ths = table.querySelectorAll('thead th')
							const monthName = ths[cellIndex]?.textContent?.trim()
							const months = [
								'январь',
								'февраль',
								'март',
								'апрель',
								'май',
								'июнь',
								'июль',
								'август',
								'сентябрь',
								'октябрь',
								'ноябрь',
								'декабрь',
							]
							const monthIndex = months.findIndex(
								m => m.toLowerCase() === monthName.toLowerCase()
							)
							const year =
								ths[cellIndex]?.dataset?.year || new Date().getFullYear()
							if (monthIndex !== -1) {
								createdAt = `${String(monthIndex + 1).padStart(2, '0')}.${year}`
							}
						}
					}

					if (selectedCell && isLastCell) {
						query = ''
					} else if (!isTotalRow && createdAt) {
						query = `?id_purpose=${idPurpose}&created_at=${createdAt}`
					} else {
						query = `?id_purpose=${idPurpose}`
					}
					window.location.href = `/cash_flow/${query}`
				} else {
					showError('Выберите строку для просмотра деталей.')
				}
			})
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

const handleExchange = () => {
	let to_us_completed
	let from_us_completed

	try {
		const dataIdsData = document.getElementById('data-ids')?.textContent
		if (dataIdsData) {
			const dataIds = JSON.parse(dataIdsData)
			setIds(dataIds.from_us, 'from_us_exchange-table')
			setIds(dataIds.to_us, 'to_us_exchange-table')

			to_us_completed = dataIds.to_us_completed || []
			from_us_completed = dataIds.from_us_completed || []

			const counted_from_us =
				Array.isArray(dataIds?.counted_from_us) &&
				dataIds.counted_from_us.length > 0
					? dataIds.counted_from_us
					: [0]

			const counted_to_us =
				Array.isArray(dataIds?.counted_to_us) &&
				dataIds.counted_to_us.length > 0
					? dataIds.counted_to_us
					: [0]

			const filteredFrom = counted_from_us.filter(
				id => !from_us_completed.includes(id)
			)

			const filteredTo = counted_to_us.filter(
				id => !to_us_completed.includes(id)
			)

			TableManager.calculateTableSummary('from_us_exchange-table', ['amount'], {
				ids: filteredFrom && filteredFrom.length > 0 ? filteredFrom : [0],
			})
			TableManager.calculateTableSummary('to_us_exchange-table', ['amount'], {
				ids: filteredTo,
			})

			highlightExchangeTotals(counted_from_us)

			hideCompletedExchangeRows(from_us_completed, to_us_completed)
		} else {
			console.warn("Element with ID 'data-ids' not found or empty.")
		}
	} catch (e) {
		console.error(
			'Error parsing money transfers IDs data for actions column:',
			e
		)
	}

	const addExchangeFormHandler = createExchangeFormHandler('add')
	const editExchangeFormHandler = createExchangeFormHandler('edit')
	const deleteExchangeFormHandler = createExchangeFormHandler('delete')
	let transferType = null

	document.addEventListener('contextmenu', function (e) {
		const fromUsBlock = e.target.closest('#from-us-exchange')
		const toUsBlock = e.target.closest('#to-us-exchange')

		if (fromUsBlock) {
			transferType = 'from_us'

			addExchangeFormHandler.tableId = 'from_us_exchange-table'
			editExchangeFormHandler.tableId = 'from_us_exchange-table'
			deleteExchangeFormHandler.tableId = 'from_us_exchange-table'
		} else if (toUsBlock) {
			transferType = 'to_us'

			addExchangeFormHandler.tableId = 'to_us_exchange-table'
			editExchangeFormHandler.tableId = 'to_us_exchange-table'
			deleteExchangeFormHandler.tableId = 'to_us_exchange-table'
		}

		const tableRow = e.target.closest('tr')
		const dataId = tableRow ? tableRow.dataset.id : null
	})

	const addButton = document.getElementById('add-button')
	const editButton = document.getElementById('edit-button')
	const deleteButton = document.getElementById('delete-button')

	if (addButton) {
		addButton.addEventListener('click', async function (e) {
			await addExchangeFormHandler.init(0)

			setupMultipleSupplierAccountSelects([
				{ supplierId: 'source_supplier', accountId: 'source_account' },
				{
					supplierId: 'destination_supplier',
					accountId: 'destination_account',
				},
			])
		})
	}

	if (editButton) {
		editButton.addEventListener('click', async function (e) {
			const rowId = TableManager.getSelectedRowId(
				editExchangeFormHandler.tableId
			)

			if (rowId) {
				if (
					(from_us_completed &&
						from_us_completed.map(String).includes(String(rowId))) ||
					(to_us_completed &&
						to_us_completed.map(String).includes(String(rowId)))
				) {
					showError('Нельзя редактировать завершённый обмен!')
					return
				}

				await editExchangeFormHandler.init(rowId)

				setupMultipleSupplierAccountSelects([
					{ supplierId: 'source_supplier', accountId: 'source_account' },
					{
						supplierId: 'destination_supplier',
						accountId: 'destination_account',
					},
				])
			} else {
				showError('Выберите строку для редактирования!')
			}
		})
	}

	if (deleteButton) {
		deleteButton.addEventListener('click', async function (e) {
			const rowId = TableManager.getSelectedRowId(
				deleteExchangeFormHandler.tableId
			)

			if (rowId) {
				if (
					(from_us_completed &&
						from_us_completed.map(String).includes(String(rowId))) ||
					(to_us_completed &&
						to_us_completed.map(String).includes(String(rowId)))
				) {
					showError('Нельзя удалять завершённый обмен!')
					return
				}

				showQuestion(
					'Вы действительно хотите удалить запись?',
					'Удаление',
					async () => {
						const result = await TableManager.sendDeleteRequest(
							rowId,
							deleteExchangeFormHandler.config.submitUrl,
							deleteExchangeFormHandler.tableId
						)

						if (result && result.status === 'success') {
							let counted_from_us =
								result.transfer_type === 'from_us'
									? Array.isArray(result?.counted_from_us) &&
									  result.counted_from_us.length > 0
										? result.counted_from_us
										: [0]
									: []

							TableManager.calculateTableSummary(
								result.transfer_type === 'from_us'
									? 'from_us_exchange-table'
									: 'to_us_exchange-table',
								['amount'],
								{
									ids:
										result.transfer_type === 'from_us' ? counted_from_us : [],
								}
							)
							let to_us_completed = result.to_us_completed || []
							let from_us_completed = result.from_us_completed || []

							const counted_to_us =
								Array.isArray(result?.counted_to_us) &&
								result.counted_to_us.length > 0
									? result.counted_to_us
									: [0]

							const filteredFrom = counted_from_us.filter(
								id => !from_us_completed.includes(id)
							)

							const filteredTo = counted_to_us.filter(
								id => !to_us_completed.includes(id)
							)

							TableManager.calculateTableSummary(
								'from_us_exchange-table',
								['amount'],
								{
									ids:
										filteredFrom && filteredFrom.length > 0
											? filteredFrom
											: [0],
								}
							)
							TableManager.calculateTableSummary(
								'to_us_exchange-table',
								['amount'],
								{
									ids: filteredTo,
								}
							)

							highlightExchangeTotals(counted_from_us)
						}
					}
				)
			} else {
				showError('Выберите строку для удаления!')
			}
		})
	}

	const hideButton = document.getElementById('hide-button')
	const showAllButton = document.getElementById('show-all-button')
	const hideAllButton = document.getElementById('hide-all-button')

	if (hideButton) {
		hideButton.addEventListener('click', function () {
			const tableId =
				transferType === 'from_us'
					? 'from_us_exchange-table'
					: 'to_us_exchange-table'
			const rowId = TableManager.getSelectedRowId(tableId)
			if (rowId) {
				toggleExchangeRowVisibility(rowId, tableId)
			}
		})
	}

	if (showAllButton) {
		showAllButton.addEventListener('click', function () {
			toggleAllExchangeRows(true, 'from_us_exchange-table', from_us_completed)
			toggleAllExchangeRows(true, 'to_us_exchange-table', to_us_completed)
		})
	}

	if (hideAllButton) {
		hideAllButton.addEventListener('click', function () {
			toggleAllExchangeRows(false, 'from_us_exchange-table', from_us_completed)
			toggleAllExchangeRows(false, 'to_us_exchange-table', to_us_completed)
		})
	}

	const exchangeSummaryButton = document.getElementById(
		'exchange-summary-button'
	)
	if (exchangeSummaryButton) {
		exchangeSummaryButton.addEventListener('click', async function () {
			showQuestion(
				'Вы действительно хотите завершить все переводы?',
				'Завершение обмена',
				async () => {
					try {
						const response = await fetch('/money_transfers/complete_all/', {
							method: 'POST',
							headers: {
								'X-CSRFToken': getCSRFToken(),
								'Content-Type': 'application/json',
							},
						})
						if (!response.ok) {
							const errorText = await response.json()
							showError(errorText.message || 'Ошибка завершения переводов.')
							return
						}
						const fromRows = document.querySelectorAll(
							'#from_us_exchange-table tbody tr:not(.table__row--summary)'
						)
						const toRows = document.querySelectorAll(
							'#to_us_exchange-table tbody tr:not(.table__row--summary)'
						)
						fromRows.forEach(row => row.classList.add('hidden-row'))
						toRows.forEach(row => row.classList.add('hidden-row'))
					} catch (e) {
						showError('Ошибка завершения переводов.')
					}
				}
			)
		})
	}
}

function renderBalance(data) {
	const assetsTotal =
		data?.assets !== undefined
			? formatAmount(data.assets)
			: formatAmount(data?.assets_total || 0)
	const liabilitiesTotal =
		data?.liabilities?.total !== undefined
			? formatAmount(data.liabilities.total)
			: formatAmount(0)

	const mapItems = items =>
		Array.isArray(items)
			? items.map(i => ({
					name: i.branch ?? i.name ?? i.title ?? '-',
					amount: i.amount ?? i.total ?? 0,
					formatted: i.formatted_total ?? null,
					table_html: i.table_html ?? i.html ?? null,
			  }))
			: []

	const inventory = mapItems(data?.current_assets?.inventory?.items)
	const debtors = mapItems(data?.current_assets?.debtors?.items)
	const cash = mapItems(data?.current_assets?.cash?.items)

	const inventoryOptions = {}
	if (data?.current_assets?.inventory?.html)
		inventoryOptions.table_html = data.current_assets.inventory.html
	else if (data?.current_assets?.inventory?.table_html)
		inventoryOptions.table_html = data.current_assets.inventory.table_html
	else if (data?.current_assets?.inventory?.formatted_total)
		inventoryOptions.formatted = data.current_assets.inventory.formatted_total

	const debtorsOptions = {}
	if (data?.current_assets?.debtors?.html)
		debtorsOptions.table_html = data.current_assets.debtors.html
	else if (data?.current_assets?.debtors?.table_html)
		debtorsOptions.table_html = data.current_assets.debtors.table_html
	else if (data?.current_assets?.debtors?.formatted_total)
		debtorsOptions.formatted = data.current_assets.debtors.formatted_total

	const cashOptions = {}
	if (data?.current_assets?.cash?.html)
		cashOptions.table_html = data.current_assets.cash.html
	else if (data?.current_assets?.cash?.table_html)
		cashOptions.table_html = data.current_assets.cash.table_html
	else if (data?.current_assets?.cash?.formatted_total)
		cashOptions.formatted = data.current_assets.cash.formatted_total

	let liabilitiesHtml = ''
	if (Array.isArray(data?.liabilities?.items)) {
		liabilitiesHtml = data.liabilities.items
			.map(item => {
				const opt = {}
				if (item.formatted_total) opt.formatted = item.formatted_total

				const nestedItems = Array.isArray(item.items)
					? item.items.map(i => ({
							name: i.branch ?? i.name ?? i.title ?? '-',
							amount: i.amount ?? i.total ?? 0,
							formatted: i.formatted_total ?? null,
					  }))
					: null

				if (item.name === 'Нераспределенная прибыль') {
					return renderSimple(item.name, item.amount ?? 0, opt)
				}

				if (nestedItems && nestedItems.length > 0) {
					return renderGroup(
						item.name,
						item.amount ?? 0,
						nestedItems,
						'name',
						opt
					)
				}

				if (item.html || item.table_html) {
					opt.table_html = item.html || item.table_html
					return renderGroup(item.name, item.amount ?? 0, null, 'name', opt)
				}

				return renderGroup(item.name, item.amount ?? 0, null, 'name', opt)
			})
			.join('')
	} else {
		liabilitiesHtml = renderGroup(
			'Пассивы',
			data?.liabilities?.total ?? 0,
			null,
			'name',
			{
				formatted: data?.liabilities?.formatted_total,
			}
		)
	}

	return `
        <div>
            <div class="debtors-header">
                <h2 class="debtors-office-list__header">Активы</h2>
                <span class="debtors-total">${assetsTotal}</span>
            </div>

            <ul class="debtors-office-list">
                ${renderGroup(
									'ТМЦ',
									data?.current_assets?.inventory?.total ?? 0,
									inventory,
									'name',
									inventoryOptions
								)}
                ${renderGroup(
									'Дебиторская задолженность',
									data?.current_assets?.debtors?.total ?? 0,
									debtors,
									'name',
									debtorsOptions
								)}
                ${renderGroup(
									'Денежные средства',
									data?.current_assets?.cash?.total ?? 0,
									cash,
									'name',
									cashOptions
								)}
            </ul>

            <div class="debtors-header">
                <h2 class="debtors-office-list__header">Пассивы</h2>
                <span class="debtors-total">${liabilitiesTotal}</span>
            </div>

            <ul class="debtors-office-list">
                ${liabilitiesHtml}
                ${renderSimple(
									'Капитал',
									data?.capital ?? data?.liabilities?.capital?.value ?? 0,
									{
										formatted:
											data?.liabilities?.capital?.formatted ??
											data?.capital?.formatted,
									}
								)}
            </ul>
        </div>
    `
}

function renderSimple(title, total, options = {}) {
	const totalHtml =
		options.formatted !== undefined
			? `<span class="debtors-office-list__amount">${options.formatted}</span>`
			: total !== null && total !== undefined
			? `<span class="debtors-office-list__amount">${formatAmount(
					total
			  )}</span>`
			: ''

	return `
        <li class="debtors-office-list__item">
            <div class="debtors-office-list__row">
                <span class="debtors-office-list__title">${title}</span>
                ${totalHtml}
            </div>
        </li>
    `
}

function renderGroup(title, total, items, nameKey = 'name', options = {}) {
	let detailsHtml = ''

	if (items && items.length > 0) {
		detailsHtml = items
			.map(
				i =>
					`<div class="debtors-office-list__row-item">
                        <h4>${
													i[nameKey] ?? i.name ?? '-'
												}</h4> <span>${formatAmount(i.amount)}</span>
                    </div>`
			)
			.join('')
	} else {
		const tableHtml = options.html || options.table_html
		if (tableHtml) {
			detailsHtml =
				tableHtml ||
				'<div class="debtors-office-list__row-item debtors-office-list__empty">Нет данных</div>'
		} else {
			detailsHtml = `<div class="debtors-office-list__row-item debtors-office-list__empty">Нет данных</div>`
		}
	}

	const totalHtml =
		options.formatted !== undefined
			? `<span class="debtors-office-list__amount">${options.formatted}</span>`
			: total !== null && total !== undefined
			? `<span class="debtors-office-list__amount">${formatAmount(
					total
			  )}</span>`
			: ''

	const loadedAttr =
		options.html || options.table_html || (items && items.length > 0)
			? ' data-loaded="1"'
			: ''

	return `
        <li class="debtors-office-list__item">
            <div class="debtors-office-list__row">
                <button class="debtors-office-list__toggle">+</button>
                <span class="debtors-office-list__title">${title}</span>
                ${totalHtml}
            </div>
            <div class="debtors-office-list__details"${loadedAttr}>
                ${detailsHtml}
            </div>
        </li>
    `
}

function initBalanceInsertedTables() {
	const balanceTableIds = [
		'inventory-table',
		'debtors-table',
		'accounts-table',
		'credits-table',
		'short-term-table',
		'investors-table',
	]
	balanceTableIds.forEach(id => {
		const table = document.getElementById(id)
		if (table) {
			if (typeof TableManager.initTable === 'function') {
				TableManager.initTable(id)
			}
			if (typeof TableManager.formatCurrencyValues === 'function') {
				try {
					TableManager.formatCurrencyValues(id)
				} catch (e) {}
			}
		}
	})
}

function formatAmount(value) {
	if (value === null || value === undefined || value === '') {
		return '0 р.'
	}
	let num = Number(value)
	if (Number.isInteger(num)) {
		return num.toLocaleString('ru-RU', { maximumFractionDigits: 0 }) + ' р.'
	}
	if (num === 0) {
		return '0 р.'
	}
	return (
		num.toLocaleString('ru-RU', {
			minimumFractionDigits: 0,
			maximumFractionDigits: 2,
		}) + ' р.'
	)
}

const handleDebtors = async () => {
	document
		.querySelectorAll('.debtors-office-list__amount, .debtors-total')
		.forEach(el => {
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
											setIds(data.repayment_ids, data.repayments_table_id)
											if (
												data.transactions_table_id !==
													'branch-transactions-Филиал_1' &&
												data.transactions_table_id !==
													'branch-transactions-Наши_ИП'
											) {
												TableManager.calculateTableSummary(
													data.transactions_table_id,
													['supplier_debt']
												)
											}
										}

										if (tableId === data.repayments_table_id) {
											const rows = Array.from(
												table.querySelectorAll(
													'tbody tr:not(.table__row--summary)'
												)
											)

											if (rows.length > 10) {
												rows.slice(0, rows.length - 10).forEach(row => {
													row.classList.add('hidden-row')
												})
												rows.slice(-10).forEach(row => {
													row.classList.remove('hidden-row')
												})
											} else {
												rows.forEach(row => row.classList.remove('hidden-row'))
											}
										}
									}
								}
							)
						} else if (value === 'Инвесторам') {
							details.innerHTML =
								'<div class="debtors-details-title">Прибыль</div>' +
								data.html +
								'<div class="debtors-details-title">Инвесторы</div>' +
								(data.html_investors || '') +
								`<div class="debtors-office-list__row" data-target="investor-operations-details">
									<button class="debtors-office-list__toggle" type="button" aria-label="Подробнее">+</button>
									<span class="debtors-details-title">Операции</span>
								</div>
								<div class="debtors-office-list__details" id="investor-operations-details" style="display:none;">
									${data.html_operations || ''}
								</div>`

							const operationsRow = details.querySelector(
								'[data-target="investor-operations-details"]'
							)
							const operationsDetails = details.querySelector(
								'#investor-operations-details'
							)
							if (operationsRow && operationsDetails) {
								operationsRow.addEventListener('click', function () {
									const btn = operationsRow.querySelector(
										'.debtors-office-list__toggle'
									)
									btn.classList.toggle('open')
									const isOpen = operationsDetails.style.display !== 'none'
									operationsDetails.style.display = isOpen ? 'none' : 'block'
								})
							}

							const profitTable = details.querySelector(`#${data.table_id}`)
							if (profitTable) {
								const tbody = profitTable.querySelector('.table__body')
								if (tbody && !tbody.children.length) {
									const emptyRow = document.createElement('tr')
									emptyRow.className = 'table__row table__row--empty'
									const td = document.createElement('td')
									td.colSpan =
										profitTable.querySelectorAll('thead th').length || 1
									td.className = 'table__cell table__cell--empty'
									td.textContent = 'Нет данных'
									emptyRow.appendChild(td)
									tbody.appendChild(emptyRow)
								} else {
									setIds(data.data_ids, data.table_id)
								}
							}

							const investorsTable = details.querySelector('#investors-table')
							if (investorsTable) {
								const tbody = investorsTable.querySelector('.table__body')
								if (tbody && !tbody.children.length) {
									const emptyRow = document.createElement('tr')
									emptyRow.className = 'table__row table__row--empty'
									const td = document.createElement('td')
									td.colSpan =
										investorsTable.querySelectorAll('thead th').length || 1
									td.className = 'table__cell table__cell--empty'
									td.textContent = 'Нет данных'
									emptyRow.appendChild(td)
									tbody.appendChild(emptyRow)
								} else {
									setIds(data.investor_ids, 'investors-table')

									TableManager.calculateTableSummary('investors-table', [
										'balance',
									])
								}
							}

							const operationsTable = details.querySelector(
								'#investor-operations-table'
							)
							if (operationsTable) {
								const tbody = operationsTable.querySelector('.table__body')
								if (tbody && !tbody.children.length) {
									const emptyRow = document.createElement('tr')
									emptyRow.className = 'table__row table__row--empty'
									const td = document.createElement('td')
									td.colSpan =
										operationsTable.querySelectorAll('thead th').length || 1
									td.className = 'table__cell table__cell--empty'
									td.textContent = 'Нет данных'
									emptyRow.appendChild(td)
									tbody.appendChild(emptyRow)
								} else {
									setIds(data.operation_ids, 'investor-operations-table')
								}
							}
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
						TableManager.attachGlobalCellClickHandler()

						const table = details.querySelector('table')

						if (table && table.id.startsWith('branch-transactions-')) {
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
						}

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

	const balanceContainer = document.getElementById('balance-container')

	if (balanceContainer) {
		try {
			const response = await fetch('/company_balance_stats/')
			if (!response.ok) throw new Error('Ошибка запроса')
			const data = await response.json()

			balanceContainer.innerHTML = renderBalance(data)
			initBalanceInsertedTables()
			if (
				typeof TableManager !== 'undefined' &&
				TableManager &&
				typeof TableManager.init === 'function'
			) {
				TableManager.init()
			}

			balanceContainer
				.querySelectorAll('.debtors-office-list__row')
				.forEach(row => {
					row.addEventListener('click', () => {
						const details = row
							.closest('.debtors-office-list__item')
							.querySelector('.debtors-office-list__details')
						const btn = row.querySelector('.debtors-office-list__toggle')
						if (!details) return
						if (!btn) return
						btn.classList.toggle('open')
						details.classList.toggle('open')
					})
				})

			function drawCharts() {
				const statsChart = document.getElementById('statsChart')
				const profitChart = document.getElementById('profitChart')
				if (
					!statsChart ||
					!profitChart ||
					!window.lastBalanceData ||
					!window.lastBalanceData.capitals_by_month
				)
					return

				const data = window.lastBalanceData
				const statsCtx = statsChart.getContext('2d')
				const profitCtx = profitChart.getContext('2d')

				function getNiceMax(value) {
					if (value <= 10) return 10
					if (value <= 100) return Math.ceil(value / 10) * 10
					if (value <= 1000) return Math.ceil(value / 100) * 100
					if (value <= 10000) return Math.ceil(value / 500) * 500
					if (value <= 100000) return Math.ceil(value / 1000) * 1000
					if (value <= 1000000) return Math.ceil(value / 50000) * 50000
					return Math.ceil(value / 100000) * 100000
				}

				const maxValue = Math.max(...data.capitals_by_month.capitals)
				const yMax = getNiceMax(maxValue * 1.1)

				window.capitalChart = new Chart(statsCtx, {
					type: 'bar',
					data: {
						labels: data.capitals_by_month.months,
						datasets: [
							{
								label: '',
								data: data.capitals_by_month.capitals,
								backgroundColor: 'rgba(54, 162, 235, 0.5)',
								borderColor: 'rgba(54, 162, 235, 1)',
								borderWidth: 1,
								stepped: true,
							},
						],
					},
					options: {
						scales: {
							x: {
								ticks: {
									font: {
										size: 10,
									},
									maxRotation: 45,
									minRotation: 0,
									autoSkip: true,
									autoSkipPadding: 2,
								},
							},
							y: {
								beginAtZero: true,
								max: yMax,
							},
						},
						plugins: {
							legend: { display: false },
							tooltip: {
								enabled: false,
							},
							datalabels: {
								anchor: 'end',
								align: 'end',
								font: { size: 10, weight: 'bold' },
								color: '#1976d2',
								formatter: value => value,
							},
						},
					},
					plugins: [ChartDataLabels],
				})

				const yMaxProfit = getNiceMax((data.capitals_by_month.total || 0) * 1.1)

				window.profitChartInstance = new Chart(profitCtx, {
					type: 'bar',
					data: {
						labels: ['%'],
						datasets: [
							{
								label: 'Итого',
								data: [data.capitals_by_month.total],
								backgroundColor: 'rgba(255, 99, 132, 0.5)',
								borderColor: 'rgba(255, 99, 132, 1)',
								borderWidth: 1,
							},
						],
					},
					options: {
						scales: {
							y: { beginAtZero: true, display: false, max: yMaxProfit },
						},
						plugins: {
							legend: { display: false },
							tooltip: {
								enabled: false,
							},
							datalabels: {
								anchor: 'end',
								align: 'end',
								font: { size: 10, weight: 'bold' },
								color: '#1976d2',
								formatter: value => value,
							},
						},
					},
					plugins: [ChartDataLabels],
				})
			}

			function resizeCharts() {
				const statsChart = document.getElementById('statsChart')
				const profitChart = document.getElementById('profitChart')
				if (!statsChart || !profitChart) return
				const w = statsChart.parentElement.offsetWidth
				let h = 264
				let profitW = 40
				if (window.innerWidth <= 600) {
					h = 200
					profitW = 35
				} else if (window.innerWidth <= 1024) {
					h = 180
				}
				statsChart.width = w
				statsChart.height = h

				profitChart.width = profitW
				profitChart.height = h

				if (window.capitalChart) {
					window.capitalChart.destroy()
					window.capitalChart = null
				}
				if (window.profitChartInstance) {
					window.profitChartInstance.destroy()
					window.profitChartInstance = null
				}
				if (window.drawCharts) {
					window.drawCharts()
				}
			}
			window.drawCharts = drawCharts

			if (data.capitals_by_month) {
				window.lastBalanceData = data
				resizeCharts()
			}

			const dataIdsData = data.ids
			if (dataIdsData) {
				setIds(dataIdsData.credit_ids, 'credits-table')
				setIds(dataIdsData.short_ids, 'short-term-table')
				setIds(dataIdsData.inventory_ids, 'inventory-table')
			} else {
				console.warn("Element with ID 'data-ids' not found or empty.")
			}
		} catch (error) {
			console.error('Ошибка при загрузке данных:', error)
			balanceContainer.innerHTML = '<p>Ошибка при загрузке данных.</p>'
		}
	} else {
		const debtorsData = document.querySelector('.debtors-data')
		const statsContainer = document.querySelector('.stats-container')
		if (statsContainer) {
			statsContainer.style.display = 'none'
		}
		if (debtorsData) {
			debtorsData.style.maxHeight = '100%'
			debtorsData.style.border = 'none'
		}
	}

	const refreshStatsButton = document.getElementById('refresh-stats-button')
	if (refreshStatsButton) {
		refreshStatsButton.addEventListener('click', async function () {
			const balanceContainer = document.getElementById('balance-container')
			if (!balanceContainer) return

			const loader = createLoader()
			document.body.appendChild(loader)

			try {
				const response = await fetch('/company_balance_stats/')
				if (!response.ok) throw new Error('Ошибка запроса')
				const data = await response.json()

				balanceContainer.innerHTML = renderBalance(data)
				initBalanceInsertedTables()

				balanceContainer
					.querySelectorAll('.debtors-office-list__row')
					.forEach(row => {
						row.addEventListener('click', () => {
							const details = row
								.closest('.debtors-office-list__item')
								.querySelector('.debtors-office-list__details')
							const btn = row.querySelector('.debtors-office-list__toggle')
							btn.classList.toggle('open')
							details.classList.toggle('open')
						})
					})

				if (window.capitalChart) {
					window.capitalChart.destroy()
					window.capitalChart = null
				}
				if (window.profitChartInstance) {
					window.profitChartInstance.destroy()
					window.profitChartInstance = null
				}

				window.lastBalanceData = data
				if (typeof window.resizeCharts === 'function') {
					window.resizeCharts()
				}
				if (typeof window.drawCharts === 'function') {
					window.drawCharts()
				}
			} catch (error) {
				console.error('Ошибка при загрузке данных:', error)
				balanceContainer.innerHTML = '<p>Ошибка при загрузке данных.</p>'
			} finally {
				loader.remove()
			}
		})
	}

	const officeList = document.querySelectorAll('.debtors-office-list')
	if (officeList.length === 1) {
		const rows = officeList[0].querySelectorAll('.debtors-office-list__row')
		if (rows.length === 1) {
			rows[0].click()
		}
	}
	const settleDebtButton = document.getElementById('settle-debt-button')

	if (settleDebtButton) {
		settleDebtButton.addEventListener('click', async function (e) {
			e.preventDefault()
			let type = settleDebtButton.dataset.type

			let selectedRow
			let table
			let currentRowId = -1
			if (!type || type === 'balance' || type === 'initial') {
				selectedRow = document.querySelector('td.table__cell--selected')
				table = selectedRow ? selectedRow.closest('table') : null
				currentRowId = TableManager.getSelectedRowId(table.id)

				if (!type) {
					if (table.id === 'investors-table') {
						type = 'investors'
					} else {
						type = 'transactions'
						if (table && table.id === 'summary-bonus') type += '.bonus'
						else if (table && table.id === 'summary-remaining')
							type += '.remaining'
						else if (table && table.id === 'summary-profit')
							type += '.investors'
					}
				}
			} else {
				if (type === 'Оборудование') type = 'equipment'
				else if (type === 'Кредит') type = 'credit'
				else if (type === 'Краткосрочные обязательства')
					type = 'short_term_liabilities'
			}

			const getUrl = `${BASE_URL}${SUPPLIERS}/debtors/${type}/`

			const settleDebtFormHandler = createFormHandler(
				`${BASE_URL}${SUPPLIERS}/settle-debt/`,
				`debtors-table`,
				`settle-debt-form`,
				getUrl,
				type === 'investors' || type === 'initial' || type === 'balance'
					? [
							{
								id: 'operation_type',
								url: [
									{ id: 'deposit', name: 'Внесение' },
									{ id: 'withdrawal', name: 'Забор' },
								],
							},
					  ]
					: table && table.id === 'summary-profit'
					? [
							{
								id: 'investor_select',
								url: `${BASE_URL}investors/list/`,
							},
					  ]
					: [],
				{
					url:
						type === 'investors' || type === 'initial' || type === 'balance'
							? '/components/main/debt_operation_investor/'
							: '/components/main/settle-debt/',
					title: [
						'Оборудование',
						'Кредит',
						'Краткосрочные обязательства',
					].includes(type)
						? 'Изменение суммы'
						: type === 'investors'
						? 'Изменение суммы'
						: 'Погашение долга',
					...(mainConfig.modalConfig.context
						? { context: mainConfig.modalConfig.context }
						: {}),
				},
				result => {
					if (result.html || result.html_debt_repayments) {
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

								if (Array.isArray(result.html_debt_repayments)) {
									result.html_debt_repayments.forEach(html => {
										TableManager.addTableRow(
											{ html },
											`branch-repayments-${result.branch}`
										)
									})
								} else if (result.html_debt_repayments) {
									TableManager.addTableRow(
										{ html: result.html_debt_repayments },
										`branch-repayments-${result.branch}`
									)
								}

								if (Array.isArray(result.changed_html_rows)) {
									const transactionsTable = document.getElementById(tableId)
									if (transactionsTable) {
										result.changed_html_rows.forEach((htmlRow, idx) => {
											const id = result.changed_ids[idx]
											TableManager.updateTableRow(
												{ html: htmlRow, id },
												tableId
											)

											const row = TableManager.getRowById(id, tableId)
											TableManager.formatCurrencyValuesForRow(tableId, row)
										})
									}
								}

								const table = document.getElementById(
									`branch-repayments-${result.branch}`
								)
								if (table) {
									table
										.querySelectorAll('tr.table__row--empty')
										.forEach(row => row.remove())

									const rows = table.querySelectorAll('tbody tr')
									if (rows.length > 0) {
										const newRow = rows[rows.length - 1]
										newRow.setAttribute('data-id', result.debt_repayment_id)
									}
								}

								break
							case 'balance_investor':
								tableId = 'investors-table'

								TableManager.addTableRow(
									{ html: result.html_investor_debt_operation },
									`investor-operations-table`
								)

								const table_investors = document.getElementById(
									`investor-operations-table`
								)
								if (table_investors) {
									table_investors
										.querySelectorAll('tr.table__row--empty')
										.forEach(row => row.remove())
								}

								break
							case 'initial':
								tableId = 'investors-table'

								TableManager.addTableRow(
									{ html: result.html_investor_debt_operation },
									`investor-operations-table`
								)

								break
							case 'Инвесторам':
								tableId = 'summary-profit'

								TableManager.addTableRow(
									{ html: result.html_investor_debt_operation },
									`investor-operations-table`
								)

								const table_profit = document.getElementById(
									`investor-operations-table`
								)
								if (table_profit) {
									table_profit
										.querySelectorAll('tr.table__row--empty')
										.forEach(row => row.remove())

									const rows = table_profit.querySelectorAll('tbody tr')
									if (rows.length > 0) {
										const newRow = rows[rows.length - 1]
										newRow.setAttribute('data-id', result.debt_repayment_id)
									}
								}

								if (result.html_investors) {
									const investorsTable =
										document.getElementById('investors-table')
									if (investorsTable) {
										const container = investorsTable.closest('.table-container')
										if (container) {
											const wrapper = document.createElement('div')
											wrapper.innerHTML = result.html_investors
											const newContainer =
												wrapper.querySelector('.table-container')
											if (newContainer) {
												container.replaceWith(newContainer)
											}
											setIds(result.data_ids, 'investors-table')

											TableManager.initTable('investors-table')

											TableManager.calculateTableSummary(`investors-table`, [
												'balance',
											])
										}
									}
								}

								break
							default:
								tableId = `branch-transactions-${result.branch}`
						}

						const debtsHeader = document.getElementById(
							result.total_summary_debts !== undefined &&
								result.total_summary_debts !== null
								? 'summary-header'
								: 'branch-debts-header'
						)

						if (
							debtsHeader &&
							result.branch !== 'Филиал_1' &&
							result.branch !== 'Наши_ИП'
						) {
							const totalSpan = debtsHeader.querySelector('span.debtors-total')
							if (totalSpan) {
								let number = Number(
									result.total_summary_debts || result.total_branch_debts || 0
								)
								if (!isNaN(number)) {
									let formatted = number
										.toLocaleString('ru-RU')
										.replace(/,/g, ' ')
									let text = formatted
									if (!text.endsWith('р.') && !text.endsWith('р')) {
										text = text + ' р.'
									}
									totalSpan.textContent = text

									if (number === 0) {
										totalSpan.classList.remove('text-red')
										totalSpan.classList.add('text-green')
									} else {
										totalSpan.classList.remove('text-green')
										totalSpan.classList.add('text-red')
									}
								}
							}
						}

						if (result.html) {
							TableManager.updateTableRow(result, tableId)
						}

						if (result.type === 'Поставщики') {
							if (result.branch !== 'Филиал_1' && result.branch !== 'Наши_ИП') {
								TableManager.calculateTableSummary(
									`branch-transactions-${result.branch}`,
									['supplier_debt']
								)
							}
						} else if (
							result.type === 'Инвесторы' ||
							result.type === 'investors' ||
							result.type === 'balance_investor' ||
							result.type === 'initial'
						) {
							TableManager.calculateTableSummary('investors-table', ['balance'])
						}

						if (result.type === 'initial') {
						}

						refreshData(tableId)

						if (result.id) {
							const row = TableManager.getRowById(result.id, tableId)
							TableManager.formatCurrencyValuesForRow(tableId, row)
							hideDebtorRowIfNoDebt(row, tableId, result.type)
						}

						const table = document.getElementById(tableId)
						if (table) {
							if (table && table.id.startsWith('branch-transactions-')) {
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
							}
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
								} else if (
									result.type === 'Инвесторам' ||
									result.type === 'investors' ||
									result.type === 'profit'
								) {
									branchKey = 'Инвесторам'
								}
							}

							if (
								branchKey &&
								branchKey !== 'Филиал_1' &&
								branchKey !== 'Наши_ИП'
							) {
								const branchSpan = branchSpans.find(
									span =>
										span.textContent.trim() ===
										branchKey.replace(/_/g, ' ').trim()
								)
								if (branchSpan) {
									const amountSpan = branchSpan.parentElement.querySelector(
										'.debtors-office-list__amount'
									)
									if (amountSpan) {
										let debt = Number(result.total_debt)
										if (!isNaN(debt)) {
											let formatted = debt
												.toLocaleString('ru-RU')
												.replace(/,/g, ' ')
											formatted = formatted.replace(/,00$/, '')
											if (
												!formatted.endsWith('р.') &&
												!formatted.endsWith('р')
											) {
												formatted = formatted + ' р.'
											}
											amountSpan.textContent = formatted

											if (debt === 0) {
												amountSpan.classList.remove('text-red')
												amountSpan.classList.add('text-green')

												const selectedRow = document.querySelector(
													'tr.table__row--selected'
												)
												if (selectedRow) {
													selectedRow.classList.remove('table__row--selected')
													selectedRow.classList.add('hidden-row')
												}
											} else {
												amountSpan.classList.remove('text-green')
												amountSpan.classList.add('text-red')
											}
										}
									}
								}
							}
						}

						if (result.total_profit !== undefined) {
							const investorSpan = Array.from(
								document.querySelectorAll('.debtors-office-list__title')
							).find(span => span.textContent.trim() === 'Инвесторам')

							if (investorSpan) {
								const amountSpan = investorSpan.parentElement.querySelector(
									'.debtors-office-list__amount'
								)
								if (amountSpan) {
									let profit = Number(result.total_profit)
									if (!isNaN(profit)) {
										let formatted = profit
											.toLocaleString('ru-RU')
											.replace(/,/g, ' ')
										formatted = formatted.replace(/,00$/, '')
										if (!formatted.endsWith('р.') && !formatted.endsWith('р')) {
											formatted = formatted + ' р.'
										}
										amountSpan.textContent = formatted

										if (profit === 0) {
											amountSpan.classList.remove('text-red')
											amountSpan.classList.add('text-green')
										} else {
											amountSpan.classList.remove('text-green')
											amountSpan.classList.add('text-red')
										}
									}
								}
							}
						}
					}

					if (result.type && result.type === 'balance') {
						const balanceContainer =
							document.getElementById('balance-container')
						if (balanceContainer) {
							balanceContainer.innerHTML = renderBalance(result)

							balanceContainer
								.querySelectorAll('.debtors-office-list__row')
								.forEach(row => {
									row.addEventListener('click', () => {
										const details = row
											.closest('.debtors-office-list__item')
											.querySelector('.debtors-office-list__details')
										const btn = row.querySelector(
											'.debtors-office-list__toggle'
										)
										btn.classList.toggle('open')
										details.classList.toggle('open')
									})
								})
						}
					}
				}
			)
			await settleDebtFormHandler.init(currentRowId)

			setupCurrencyInput('amount')

			if (type === 'initial') {
				const operation_type = document.getElementById('operation_type')
				if (operation_type) {
					const container = operation_type.closest('.modal-form__group')
				}
			}
			if (type === 'transactions.investors') {
				const investorSelectInput = document.getElementById('investor_select')
				if (investorSelectInput) {
					const select = investorSelectInput.closest('.select')
					const dropdown = select.querySelector('.select__dropdown')
					const firstOption = dropdown.querySelector('.select__option')
					const selectText = select.querySelector('.select__text')

					if (firstOption) {
						investorSelectInput.value = firstOption.dataset.value
						selectText.textContent = firstOption.textContent
						selectText.classList.remove('select__placeholder')
						select.classList.add('has-value')
						const event = new Event('change', { bubbles: true })
						investorSelectInput.dispatchEvent(event)
					}
				}
			}

			const typeInput = document.getElementById('type')
			if (typeInput) {
				if (table) {
					if (table.id === 'summary-bonus') {
						typeInput.value = 'bonus'
					} else if (table.id === 'summary-remaining') {
						typeInput.value = 'remaining'
					} else if (table.id.startsWith('branch-transactions')) {
						typeInput.value = 'branch'

						const comment = document.getElementById('comment')

						if (comment) {
							if (comment.tagName.toLowerCase() === 'input') {
								comment.type = 'text'
							}
							comment.removeAttribute('hidden')
						}
					} else if (table.id === 'investors-table') {
						if (type === 'balance') {
							typeInput.value = 'balance'
						} else {
							typeInput.value = 'initial'
						}
					} else if (table.id === 'summary-profit') {
						typeInput.value = 'profit'

						const investor_select = document.getElementById('investor_select')
						const investorSelectContainer = investor_select
							? investor_select.closest('.modal-form__group')
							: null

						if (investorSelectContainer) {
							investorSelectContainer.removeAttribute('hidden')
						}
					} else {
						typeInput.value = 'transactions'
					}
				} else {
					typeInput.value = type
				}
			}
		})
	}

	const settleDebtAllButton = document.getElementById('settle-debt-all-button')
	if (settleDebtAllButton) {
		settleDebtAllButton.addEventListener('click', async function (e) {
			e.preventDefault()

			await settleDebtAllFormHandler.init(-1)

			setupCurrencyInput('amount')

			const table = document.getElementById('summary-profit')
			const rows = table.querySelectorAll('tbody tr[data-id]')
			const ids = Array.from(rows).map(row => row.getAttribute('data-id'))

			const investorSelectInput = document.getElementById('investor_select')
			if (investorSelectInput) {
				const modalFormGroup = investorSelectInput.closest('.modal-form__group')
				if (modalFormGroup) {
					modalFormGroup.removeAttribute('hidden')
				}

				const select = investorSelectInput.closest('.select')
				const dropdown = select.querySelector('.select__dropdown')
				const firstOption = dropdown.querySelector('.select__option')
				const selectText = select.querySelector('.select__text')

				if (firstOption) {
					investorSelectInput.value = firstOption.dataset.value
					selectText.textContent = firstOption.textContent
					selectText.classList.remove('select__placeholder')
					select.classList.add('has-value')
					const event = new Event('change', { bubbles: true })
					investorSelectInput.dispatchEvent(event)
				}
			}

			const settleDebtForm = document.getElementById('settle-debt-form')
			if (!settleDebtForm) return

			let idsInput = settleDebtForm.querySelector('#settle-debt-all-ids')
			if (!idsInput) {
				idsInput = document.createElement('input')
				idsInput.type = 'hidden'
				idsInput.id = 'settle-debt-all-ids'
				idsInput.name = 'ids'
				settleDebtForm.appendChild(idsInput)
			}
			idsInput.value = JSON.stringify(ids)
		})
	}

	const repaymentsEditButton = document.getElementById('repayment-edit-button')
	if (repaymentsEditButton) {
		repaymentsEditButton.addEventListener('click', async function (e) {
			e.preventDefault()
			const selectedRow = document.querySelector('td.table__cell--selected')
			const table = selectedRow ? selectedRow.closest('table') : null
			const currentRowId = TableManager.getSelectedRowId(table.id)

			const settleDebtFormHandler = createFormHandler(
				`${BASE_URL}${SUPPLIERS}/repay-debt/edit/`,
				table.id,
				`debt-repay-edit-form`,
				`${BASE_URL}${SUPPLIERS}/repay-debt/`,
				[],
				{
					url: '/components/main/debt_repay_edit/',
					title: 'Редактирование выдачи',
					...(mainConfig.modalConfig.context
						? { context: mainConfig.modalConfig.context }
						: {}),
				},
				result => {
					if (result.html) {
						TableManager.updateTableRow(result, table.id)

						const row = TableManager.getRowById(result.id, table.id)
						TableManager.formatCurrencyValuesForRow(table.id, row)
					}
				}
			)

			await settleDebtFormHandler.init(currentRowId)
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

	const toggles = document.querySelectorAll('.debtors-office-list__toggle')
	toggles.forEach(btn => {
		btn.addEventListener('focus', function () {
			const row = btn.closest('.debtors-office-list__row')
			if (row) row.classList.add('row-focused')
		})
		btn.addEventListener('blur', function () {
			const row = btn.closest('.debtors-office-list__row')
			if (row) row.classList.remove('row-focused')
		})
	})

	const withdrawalButton = document.getElementById('withdrawal-button')
	const contributionButton = document.getElementById('contribution-button')
	const investOperationFormHandler = createFormHandler(
		`${BASE_URL}investors/debt-operation/`,
		`investors-table`,
		`invest_operation-form`,
		``,
		[
			{
				id: 'supplier',
				url: `${BASE_URL}suppliers/list/`,
			},
		],
		{
			url: '/components/main/add_invest_operation/',
			title: 'Операция с инвестором',
		},
		result => {
			if (result.html_investor && result.investor_id) {
				TableManager.updateTableRow(
					{ html: result.html_investor, id: result.investor_id },
					'investors-table'
				)
				const investorRow = TableManager.getRowById(
					result.investor_id,
					'investors-table'
				)
				TableManager.formatCurrencyValuesForRow('investors-table', investorRow)
				TableManager.calculateTableSummary('investors-table', ['balance'])
			}
			if (result.html_operation) {
				const tableOps = document.getElementById('investor-operations-table')
				if (tableOps) {
					const wrapper = document.createElement('tbody')
					wrapper.innerHTML = result.html_operation
					const newRow = wrapper.querySelector('tr')
					if (newRow) {
						tableOps.querySelector('tbody').appendChild(newRow)
						TableManager.formatCurrencyValuesForRow(
							'investor-operations-table',
							newRow
						)
					}
				}
			}
		}
	)

	if (withdrawalButton) {
		withdrawalButton.addEventListener('click', async e => {
			e.preventDefault()

			const selectedId = TableManager.getSelectedRowId('investors-table')
			if (!selectedId) {
				showError('Инвестор не выбран')
				return
			}

			await investOperationFormHandler.init(selectedId)

			setupSupplierAccountSelects()

			const accountSelect = document
				.getElementById('account')
				?.closest('.select')

			if (!accountSelect) return
			const dropdown = accountSelect.querySelector('.select__dropdown')
			if (!dropdown) return

			const exists = Array.from(dropdown.children).some(
				opt => opt.textContent.trim() === 'Наличные'
			)
			if (!exists) {
				const cashOption = document.createElement('div')
				cashOption.className = 'select__option'
				cashOption.tabIndex = 0
				cashOption.dataset.value = '0'
				cashOption.textContent = 'Наличные'
				dropdown.appendChild(cashOption)

				SelectHandler.attachOptionHandlers(accountSelect)
				SelectHandler.setupSelectBehavior(accountSelect)

				const input = accountSelect.querySelector('.select__input')
				const text = accountSelect.querySelector('.select__text')
				input.value = cashOption.dataset.value
				text.textContent = cashOption.textContent
				text.classList.remove('select__placeholder')
				accountSelect.classList.add('has-value')
				input.dispatchEvent(new Event('change', { bubbles: true }))
			}

			const typeInput = document.getElementById('type')
			if (typeInput) {
				typeInput.value = 'withdrawal'
				typeInput.dispatchEvent(new Event('change', { bubbles: true }))
			}

			const selectedRow = document.querySelector('.table__row--selected')

			const idInput = document.getElementById('id')
			if (selectedRow && idInput) {
				const rowId = selectedRow.getAttribute('data-id')
				if (rowId) {
					idInput.value = rowId
					idInput.dispatchEvent(new Event('change', { bubbles: true }))
				}
			}

			const investSelectsDiv = document.querySelector(
				'.add-invest-operation__selects'
			)
			if (investSelectsDiv) {
				investSelectsDiv.style.flexDirection = 'column-reverse'
			}
		})
	}

	if (contributionButton) {
		contributionButton.addEventListener('click', async e => {
			e.preventDefault()

			const selectedId = TableManager.getSelectedRowId('investors-table')
			if (!selectedId) {
				showError('Инвестор не выбран')
				return
			}

			await investOperationFormHandler.init(selectedId)

			setupSupplierAccountSelects()

			const typeInput = document.getElementById('type')
			if (typeInput) {
				typeInput.value = 'contribution'
				typeInput.dispatchEvent(new Event('change', { bubbles: true }))
			}

			const supplierInput = document.getElementById('supplier')
			if (supplierInput) {
				supplierInput.setAttribute('placeholder', 'Выберите поставщика')
				supplierInput.value = ''
				const select = supplierInput.closest('.select')
				if (select) {
					const textSpan = select.querySelector('.select__text')
					if (
						textSpan &&
						textSpan.textContent.trim() ===
							'Выберите поставщика (необязательно)'
					) {
						textSpan.textContent = 'Выберите поставщика'
					}
				}
			}
		})
	}
}

document.addEventListener('DOMContentLoaded', function () {
	TableManager.init()
	addMenuHandler()

	const globalHideAllBtn = document.getElementById('hide-all-button')
	if (globalHideAllBtn) {
		globalHideAllBtn.addEventListener('click', function (e) {
			const selectedCells = Array.from(
				document.querySelectorAll('.table__cell--selected')
			)
			if (selectedCells.length <= 1) {
				return
			}

			e.preventDefault()
			e.stopPropagation()

			const tables = new Set(
				selectedCells.map(cell => {
					const tbl = cell.closest('table')
					return tbl ? tbl.id : null
				})
			)
			if (tables.size !== 1) {
				return
			}
			const tableId = Array.from(tables)[0]
			if (!tableId) return

			selectedCells.forEach(cell => {
				const row = cell.closest('tr[data-id]')
				if (!row) return
				row.classList.toggle('hidden-row')
			})

			try {
				updateHiddenRowsCounter()
				saveHiddenRowsState(tableId)
			} catch (err) {
				console.error('Ошибка при сохранении скрытых строк:', err)
			}

			const menu = document.getElementById('context-menu')
			if (menu) menu.style.display = 'none'
		})
	}

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
			case `users`:
				handleUsers(usersConfig)
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
			case `exchange`:
				handleExchange()
				break
			case `${TRANSACTION}`:
				handleTransactions(mainConfig)
				break
			case `debtors`:
				handleDebtors()
				break
			case `balance`:
				handleDebtors()

				initBalanceAddButton()
				initBalanceEditButton()
				initBalanceDeleteButton()
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
		restoreHiddenRowsState(`${TRANSACTION}-table`)
		updateHiddenRowsCounter()
	}
})
