import { DynamicFormHandler } from '/static/js/dynamicFormHandler.js'
import { TableManager } from '/static/js/table.js'
import { showError, showQuestion } from '/static/js/ui-utils.js'

export function initTableHandlers(config) {
	const container = document.getElementById(config.containerId)
	if (!container) return
	const table = document.getElementById(config.tableId)
	if (!table) return

	const hasModalConfig =
		config.modalConfig && typeof config.modalConfig === 'object'
	const addModalUrl = hasModalConfig
		? config.modalConfig.addModalUrl
		: config.addModalUrl
	const editModalUrl = hasModalConfig
		? config.modalConfig.editModalUrl
		: config.editModalUrl
	const addModalTitle = hasModalConfig
		? config.modalConfig.addModalTitle
		: 'Добавить запись'
	const editModalTitle = hasModalConfig
		? config.modalConfig.editModalTitle
		: 'Изменить запись'

	const addFormHandler = new DynamicFormHandler({
		dataUrls: config.dataUrls,
		submitUrl: config.addUrl,
		tableId: config.tableId,
		formId: config.formId,
		...(addModalUrl
			? {
					modalConfig: {
						url: addModalUrl,
						title: addModalTitle,
						...(config.modalConfig.context
							? { context: config.modalConfig.context }
							: {}),
					},
			  }
			: {
					createFormFunction: formId =>
						TableManager.createForm(formId, config.tableId),
			  }),
		onSuccess: result => {
			TableManager.addTableRow(result, config.tableId)

			if (config.afterAddFunc) {
				config.afterAddFunc(result)
			}
		},
	})

	const editFormHandler = new DynamicFormHandler({
		dataUrls: config.dataUrls,
		submitUrl: config.editUrl,
		tableId: config.tableId,
		formId: config.formId,
		getUrl: config.getUrl,
		...(editModalUrl
			? {
					modalConfig: {
						url: editModalUrl,
						title: editModalTitle,
						...(config.modalConfig.context
							? { context: config.modalConfig.context }
							: {}),
					},
			  }
			: {
					createFormFunction: formId =>
						TableManager.createForm(formId, config.tableId),
			  }),
		onSuccess: result => {
			TableManager.updateTableRow(result, config.tableId)

			if (config.afterEditFunc) {
				config.afterEditFunc(result)
			}
		},
	})

	if (config.refreshUrl) {
		const refreshButton = container.querySelector('#refresh-button')
		if (refreshButton) {
			refreshButton.addEventListener('click', async () => {
				await TableManager.hideForm(config.formId, config.tableId)
				await TableManager.refresh(config.refreshUrl, config.tableId)

				if (config.refreshFunc) {
					config.refreshFunc()
				}
			})
		}
	}

	const addButton = container.querySelector('#add-button')
	const editButton = container.querySelector('#edit-button')
	const deleteButton = container.querySelector('#delete-button')

	if (addButton) {
		container
			.querySelector('#add-button')
			.addEventListener('click', async () => {
				await addFormHandler.init()

				if (config.addFunc) {
					config.addFunc()
				}
			})
	}

	if (editButton) {
		container
			.querySelector('#edit-button')
			.addEventListener('click', async () => {
				const selectedRowId = TableManager.getSelectedRowId(config.tableId)

				if (selectedRowId) {
					if (!editModalUrl) {
						editFormHandler.config.createFormFunction = formId =>
							TableManager.createForm(formId, config.tableId, selectedRowId)
					}
					await editFormHandler.init(selectedRowId)

					if (config.editFunc) {
						config.editFunc()
					}
				} else {
					showError('Выберите строку для редактирования!')
				}
			})
	}

	if (deleteButton) {
		container.querySelector('#delete-button').addEventListener('click', () => {
			TableManager.hideForm(config.formId, config.tableId)
			const selectedRowId = TableManager.getSelectedRowId(config.tableId)
			if (selectedRowId) {
				showQuestion(
					'Вы действительно хотите удалить запись?',
					'Удаление',
					async () =>
						await TableManager.sendDeleteRequest(
							selectedRowId,
							config.deleteUrl,
							config.tableId
						).then(result => {
							if (config.afterDeleteFunc) {
								config.afterDeleteFunc(result)
							}
						})
				)
			} else {
				showError('Выберите строку для удаления!')
			}
		})
	}
}
