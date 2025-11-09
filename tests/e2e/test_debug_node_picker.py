"""
Simplified E2E test to debug node picker interaction issues.
"""

from playwright.sync_api import Page, expect


def test_debug_node_picker_interaction(page: Page, test_server_url: str):
    """Debug test to understand node picker interaction issues."""
    # Navigate to packets page
    page.goto(f"{test_server_url}/packets")
    page.wait_for_selector("#packetsTable", timeout=10000)
    page.wait_for_timeout(2000)  # Wait for everything to load

    print("=== PAGE LOADED ===")

    # Debug: Check initial state
    initial_state = page.evaluate("""() => {
        const excludeFromHidden = document.querySelector('input[name="exclude_from"]');
        const excludeFromVisible = document.querySelector('#exclude_from');
        return {
            hiddenInputExists: !!excludeFromHidden,
            hiddenInputValue: excludeFromHidden?.value || 'NONE',
            visibleInputExists: !!excludeFromVisible,
            visibleInputValue: excludeFromVisible?.value || 'NONE',
            containerExists: !!document.querySelector('.node-picker-container[data-include-broadcast="true"]'),
            nodePickerCount: document.querySelectorAll('.node-picker-container').length
        };
    }""")
    print(f"Initial state: {initial_state}")

    # Try to interact with the exclude_from field
    exclude_from_field = page.locator("#exclude_from")
    expect(exclude_from_field).to_be_visible()

    print("=== CLICKING EXCLUDE_FROM FIELD ===")
    exclude_from_field.click()
    page.wait_for_timeout(1000)

    # Check if the node picker activated
    picker_state = page.evaluate("""() => {
        const container = document.querySelector('#exclude_from').closest('.node-picker-container');
        const dropdown = container?.querySelector('.node-picker-dropdown');
        const textInput = container?.querySelector('input[type="text"]');
        return {
            containerFound: !!container,
            dropdownExists: !!dropdown,
            dropdownVisible: dropdown?.style.display !== 'none' && dropdown?.classList.contains('show'),
            textInputExists: !!textInput,
            textInputValue: textInput?.value || 'NONE'
        };
    }""")
    print(f"Picker state after click: {picker_state}")

    # Type search text
    search_input = (
        page.locator("#exclude_from").locator("..").locator("input[type='text']")
    )
    print("=== TYPING SEARCH TEXT ===")
    search_input.fill("Test Gateway Alpha")
    page.wait_for_timeout(2000)  # Give extra time for search

    # Check search results
    search_results = page.evaluate("""() => {
        const container = document.querySelector('#exclude_from').closest('.node-picker-container');
        const dropdown = container?.querySelector('.node-picker-dropdown');
        const results = dropdown?.querySelector('.node-picker-results');
        const items = results?.querySelectorAll('.node-picker-item');
        return {
            dropdownVisible: dropdown?.style.display !== 'none' && dropdown?.classList.contains('show'),
            resultsHTML: results?.innerHTML || 'NO RESULTS',
            itemCount: items?.length || 0,
            firstItemText: items?.[0]?.textContent?.trim() || 'NO FIRST ITEM',
            firstItemNodeId: items?.[0]?.dataset?.nodeId || 'NO NODE ID'
        };
    }""")
    print(f"Search results: {search_results}")

    if search_results["itemCount"] > 0:
        print("=== CLICKING FIRST SEARCH RESULT ===")
        # Try to click the first result using a more robust selector
        exclude_from_container = page.locator("#exclude_from").locator("..")
        first_item = exclude_from_container.locator(".node-picker-item").first

        # Wait for the item to be visible and clickable
        expect(first_item).to_be_visible()
        first_item.click()
        page.wait_for_timeout(1000)

        # Check if hidden input was set
        final_state = page.evaluate("""() => {
            const excludeFromHidden = document.querySelector('input[name="exclude_from"]');
            const excludeFromVisible = document.querySelector('#exclude_from');
            return {
                hiddenInputValue: excludeFromHidden?.value || 'NONE',
                visibleInputValue: excludeFromVisible?.value || 'NONE',
            };
        }""")
        print(f"Final state after selection: {final_state}")

        if final_state["hiddenInputValue"] != "NONE":
            print("=== SUCCESS: Hidden input was set correctly ===")

            # Now try applying the filter
            print("=== APPLYING FILTERS ===")
            apply_button = page.locator("#applyFilters")
            apply_button.click()
            page.wait_for_timeout(3000)

            # Check URL
            current_url = page.url
            print(f"URL after applying: {current_url}")

            # Check if packets were filtered
            rows_after = page.locator("#packetsTable tbody tr")
            count_after = rows_after.count()
            print(f"Packet count after filtering: {count_after}")

        else:
            print("=== FAILURE: Hidden input was not set ===")
    else:
        print("=== FAILURE: No search results found ===")


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v", "-s"])
