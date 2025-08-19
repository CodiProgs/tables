document.addEventListener('DOMContentLoaded', () => {
	const processInputContainers = () => {
		const inputContainers = document.querySelectorAll('.input-container')

		inputContainers.forEach(container => {
			const input = container.querySelector('input, textarea')
			const clearButton = container.querySelector('.clear-button')

			if (!input || !clearButton) return

			const updateClearButton = () => {
				if (input.value.trim() !== '') {
					container.classList.add('has-value')
					clearButton.style.display = 'flex'
				} else {
					container.classList.remove('has-value')
					clearButton.style.display = 'none'
				}
			}

			clearButton.addEventListener('click', () => {
				input.value = ''
				input.focus()
				updateClearButton()
			})

			input.addEventListener('input', () => {
				updateClearButton()
			})

			updateClearButton()
		})
	}

	processInputContainers()

	const observerInputs = new MutationObserver(() => {
		processInputContainers()
	})

	observerInputs.observe(document.body, { childList: true, subtree: true })
})
