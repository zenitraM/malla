/*
 * Filter Store – tiny reactive state container used by table filter widgets.
 * Can be reused by any page that needs a shared, reactive filter object.
 * Usage:
 *   const store = createFilterStore(initialState);
 *   store.subscribe(filters => { ... }); // get notified on every change (debounced in caller if desired)
 *   store.state.<key> = value; // update a single filter property
 */
(function (global) {
    "use strict";

    /**
     * Create a lightweight reactive store backed by `Proxy`.
     * @param {Object} initial - initial state values.
     * @returns {{state: Object, subscribe: Function}}
     */
    function createFilterStore(initial = {}) {
        const listeners = new Set();

        /**
         * Notify all listeners with a shallow copy of the current state.
         * @param {Object} currentState
         */
        function notify(currentState) {
            // Create a shallow copy to protect internals
            const snapshot = { ...currentState };
            listeners.forEach((fn) => {
                try { fn(snapshot); } catch (err) { console.error("FilterStore listener error", err); }
            });
        }

        const state = new Proxy({ ...initial }, {
            set(target, prop, value) {
                if (target[prop] !== value) {
                    target[prop] = value;
                    notify(target);
                }
                return true;
            }
        });

        return {
            state,
            /**
             * Subscribe to state changes.
             * @param {(state: Object) => void} fn - callback executed on every mutation.
             * @returns {() => void} Unsubscribe function.
             */
            subscribe(fn) {
                listeners.add(fn);
                // Immediately emit current state to new subscriber
                fn({ ...state });
                return () => listeners.delete(fn);
            }
        };
    }

    // Expose globally
    global.createFilterStore = createFilterStore;
})(typeof window !== "undefined" ? window : this);
