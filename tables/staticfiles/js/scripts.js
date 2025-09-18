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

	document.querySelectorAll('.nav-list .nav-item').forEach(li => {
		let timeout
		let tooltip

		li.addEventListener('touchstart', e => {
			timeout = setTimeout(() => {
				const icon = li.querySelector('.icon[data-hint]')
				if (!icon) return
				const hint = icon.dataset.hint
				tooltip = document.createElement('div')
				tooltip.className = 'icon-tooltip'
				tooltip.textContent = hint
				document.body.appendChild(tooltip)

				const rect = li.getBoundingClientRect()
				tooltip.style.left = rect.left + rect.width / 2 + 'px'
				tooltip.style.top = rect.top - 8 + 'px'
			}, 500)
		})

		li.addEventListener('touchend', e => {
			clearTimeout(timeout)
			if (tooltip) {
				tooltip.remove()
				tooltip = null
			}
		})

		li.addEventListener('touchmove', e => {
			clearTimeout(timeout)
			if (tooltip) {
				tooltip.remove()
				tooltip = null
			}
		})
	})
})
